# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Per-user sign-in for proxied MCP servers, part 2: ``auth.type: oauth_user`` (wave 7 phase 7.3).

The fake vendor is ``deployment/local-lab/fake_oauth_mcp.py`` on a local port: an OAuth authorization
server (metadata, dynamic client registration, authorize with PKCE verification, token, refresh with
rotation, revocation) and an MCP server that accepts only the access tokens it issued for itself
(resource indicator), answering 401 with ``WWW-Authenticate`` pointing at its protected-resource
metadata, and 403 ``insufficient_scope`` to a write without the write scope. Covered: configuration
rules; discovery (RFC 9728 from the 401, RFC 8414) and dynamic registration kept in the vault; two
users signing in and getting their own answers; PKCE mismatch, unknown, foreign and other-browser
``state`` refused; refresh before expiry and once after a 401; a refused refresh marks "needs
re-connect"; an operator-registered client; write scopes only for a user who opts in; revocation at
the vendor on disconnect, on disable (admin route and users-file sync) and on sign-out everywhere;
tokens never in logs, audit, status or errors; the SAJHA Net relay of the connect request; a
session-based upstream with OAuth; the pages end to end.

Design: docs/architecture/Per-User Sign-In for Proxied Servers.md
"""

import importlib.util
import json
import logging
import re
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from sqlalchemy import create_engine

from sajha.accounts.errors import ConnectedAccountRequired, OAuthFlowError
from sajha.accounts.vault import LocalKeyProvider, TokenVault, set_vault
from sajha.federation.config import ConfigError, FederationSettings, UpstreamConfig
from sajha.federation.oauth_user import CLIENT_ROW, OAuthUserError, UpstreamOAuth, set_oauth
from sajha.federation.user_tokens import ProxiedTokens, set_tokens
from sajha.observability.caller import Caller, reset, set_caller

KEY = 'test-vault-key-oauth-user-' + 'q' * 32
_spec = importlib.util.spec_from_file_location(
    'fake_oauth_mcp', Path(__file__).resolve().parents[1] / 'deployment' / 'local-lab' / 'fake_oauth_mcp.py')
fake_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fake_mod)


class Reg:
    def __init__(self):
        self.tools = {}

    def register_tool(self, t):
        self.tools[t.name] = t

    def unregister_tool(self, n):
        self.tools.pop(n, None)

    def get_tool(self, n):
        return self.tools.get(n)


class as_user:
    def __init__(self, uid):
        self.uid = uid

    def __enter__(self):
        self.t = set_caller(Caller(self.uid))

    def __exit__(self, *a):
        reset(self.t)


def wait_for(cond, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def fake():
    f = fake_mod.FakeOAuthMCP().start()
    yield f
    f.stop()


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = TokenVault(engine=create_engine(f'sqlite:///{tmp_path / "vault.db"}'), key_provider=LocalKeyProvider(KEY))
    set_vault(v)
    events = []
    monkeypatch.setattr(ProxiedTokens, 'audit', staticmethod(
        lambda action, actor, upstream_id, ip=None, **d: events.append((action, actor, upstream_id, d))))
    t = ProxiedTokens(v)
    set_tokens(t)
    t.events = events
    o = UpstreamOAuth(t)
    set_oauth(o)
    t.oauth = o
    yield t
    set_oauth(None)
    set_tokens(None)
    set_vault(None)


@pytest.fixture
def skew():
    from sajha.accounts.settings import AccountsSettings, set_accounts_settings

    def set_(seconds):
        set_accounts_settings(AccountsSettings(refresh_skew_seconds=seconds))
    yield set_
    set_accounts_settings(None)


def manager_for(tmp_path, monkeypatch, upstreams, **settings):
    from sajha.federation import manager as fm
    from sajha.federation.manager import FederationManager
    from sajha.federation.store import FederationStore
    st = FederationSettings(enabled=True, allow_localhost=True, require_approval=False, startup_wait_seconds=10,
                            default_timeout_seconds=10, upstreams=upstreams, **settings)
    reg = Reg()
    m = FederationManager(reg, st, FederationStore(str(tmp_path / f'fed-{uuid.uuid4().hex[:6]}.json')))
    monkeypatch.setattr(fm, '_manager', m)
    m.start()
    return m, reg


def oauth_user(url, uid='notes', protocol='2026-07-28', **auth):
    return {'id': uid, 'url': url, 'protocol': protocol, 'title': 'Lab notes',
            'auth': {'type': 'oauth_user', 'scopes': ['notes:read'], 'vendor': 'Lab notes', **auth}}


def sign_in(vault, fake, upstream, user, *, write=False, vendor_user=None, tamper=None):
    """The browser's part: start, approve at the fake vendor, come back with the code."""
    from sajha.routes.server_connections_routes import _after_oauth_connect
    m_cfg = UpstreamOAuth.config(upstream)
    nonce = 'nonce-' + user
    url = vault.oauth.start(m_cfg, user, browser_nonce=nonce, write=write)
    q = dict(parse_qsl(urlsplit(url).query))
    r = httpx.post(fake.issuer + '/authorize', data={**q, 'user': vendor_user or f'{user}-at-vendor',
                                                     'decision': 'allow'}, follow_redirects=False)
    assert r.status_code == 302, r.text
    back = dict(parse_qsl(urlsplit(r.headers['location']).query))
    if tamper:
        tamper(back)
    conn = vault.oauth.complete(m_cfg, user, state=back.get('state', ''), code=back.get('code', ''),
                                browser_nonce=back.pop('nonce', nonce))
    _after_oauth_connect(m_cfg, user, conn)
    return conn, q


def secrets_of(fake):
    return list(fake.access) + list(fake.refresh) + [c.get('secret') for c in fake.clients.values() if c.get('secret')]


# ── configuration ───────────────────────────────────────────────────

def test_config_rules_of_oauth_user():
    url = 'https://mcp.example.com/mcp'
    ok = UpstreamConfig.from_dict({'id': 'gh', 'url': url, 'auth': {
        'type': 'oauth_user', 'scopes': ['read:user'], 'write_scopes': ['repo'], 'vendor': 'GitHub',
        'client_id': 'Iv1.abc', 'client_secret_ref': 'env:GH_SECRET', 'authorize_url': 'https://github.com/a',
        'token_url': 'https://github.com/t', 'revoke_style': 'github', 'resource_indicator': False}})
    from sajha.federation.oauth_user import OAuthUserSpec
    spec = OAuthUserSpec.from_auth(ok.auth)
    assert spec.write_scopes == ['repo'] and spec.resource_indicator is False
    for bad, msg in [
            ({'type': 'oauth_user', 'colour': 'red'}, 'unknown'),
            ({'type': 'oauth_user', 'client_id': 'x', 'client_secret': 'inline'}, 'reference'),
            ({'type': 'oauth_user', 'client_id': 'x', 'client_secret_ref': 'plain-secret'}, 'reference'),
            ({'type': 'oauth_user', 'client_secret_ref': 'env:X'}, 'needs auth.client_id'),
            ({'type': 'oauth_user', 'client_id': 'x', 'authorize_url': 'https://a.example/a'}, 'go together'),
            ({'type': 'oauth_user', 'authorize_url': 'https://a/a', 'token_url': 'https://a/t'}, 'client_id'),
            ({'type': 'oauth_user', 'revoke_style': 'magic'}, 'revoke_style'),
            ({'type': 'oauth_user', 'token_url': 'ftp://x', 'authorize_url': 'ftp://y', 'client_id': 'c'}, 'http'),
            ({'type': 'oauth_user', 'scopes': ['a b"']}, 'space')]:
        with pytest.raises(ConfigError, match=msg):
            UpstreamConfig.from_dict({'id': 'gh', 'url': url, 'auth': bad})
    with pytest.raises(ConfigError, match='Authorization'):
        UpstreamConfig.from_dict({'id': 'gh', 'url': url, 'auth': 'oauth_user',
                                  'headers': {'Authorization': 'Bearer shared'}})


def test_the_shipped_templates_load(monkeypatch):
    """The oauth_user templates of config/mcp_servers/ are valid entries (with their client ids set)."""
    from sajha.federation.mcp_servers import parse
    monkeypatch.setenv('GITHUB_OAUTH_CLIENT_ID', 'Iv1.example')
    monkeypatch.setenv('GOOGLE_OAUTH_CLIENT_ID', 'example.apps.googleusercontent.com')
    root = Path(__file__).resolve().parents[1] / 'config' / 'mcp_servers'
    seen = 0
    for name in ('06_remote_oauth_sign_in.json.example', '13_atlassian_cloud_oauth.json.example',
                 '14_github_oauth.json.example', '15_google_workspace_oauth.json.example'):
        p = parse(json.loads((root / name).read_text()))
        assert not p.errors, (name, p.errors)
        for u in p.upstreams:
            cfg = UpstreamConfig.from_dict(u, source='file')
            assert cfg.auth.get('type') == 'oauth_user', (name, u['id'])
            seen += 1
    assert seen >= 6


# ── discovery and registration ──────────────────────────────────────

def test_discovery_from_the_401_and_dynamic_registration(tmp_path, monkeypatch, fake, vault):
    m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(fake.url)])
    try:
        assert wait_for(lambda: m.status('notes')['state'] == 'waiting_for_user')
        cfg = m.get_config('notes')
        ep = vault.oauth.endpoints(cfg)
        assert ep.issuer == fake.issuer and ep.token_url == fake.issuer + '/token'
        assert ep.resource == fake.resource and ep.registration_url and ep.revoke_url
        url = vault.oauth.start(cfg, 'alice', browser_nonce='n')
        q = dict(parse_qsl(urlsplit(url).query))
        assert url.startswith(fake.issuer + '/authorize?')
        assert q['code_challenge_method'] == 'S256' and len(q['code_challenge']) >= 43 and q['state']
        assert q['resource'] == fake.resource and q['scope'] == 'notes:read'
        assert q['redirect_uri'].endswith('/account/server-connections/oauth/callback')
        regs = [d for w, d in fake.events if w == 'register']
        assert len(regs) == 1 and regs[0]['redirect_uris'] == [q['redirect_uri']]
        vault.oauth.start(cfg, 'bob', browser_nonce='n')             # the registration is reused
        assert len([1 for w, _ in fake.events if w == 'register']) == 1
        row = vault.vault.get(CLIENT_ROW, 'upstream:notes')
        assert row is not None and vault.all_connections() == []     # never listed as a user's connection
        # an upstream whose authorization server offers no registration and no client is configured
        fake.dcr = False
        vault.oauth.forget('notes')
        vault.vault.delete(CLIENT_ROW, 'upstream:notes')
        with pytest.raises(OAuthUserError, match='dynamic client registration'):
            vault.oauth.start(cfg, 'alice', browser_nonce='n')
    finally:
        m.stop()


def test_metadata_must_be_https_and_must_offer_pkce(tmp_path, monkeypatch, fake, vault):
    from sajha.federation.oauth_user import check_oauth_url
    st = FederationSettings(allow_localhost=False)
    with pytest.raises(OAuthUserError, match='https'):
        check_oauth_url('http://127.0.0.1:1/as', 'x', st)
    with pytest.raises(OAuthUserError, match='https'):
        check_oauth_url('http://vendor.example/as', 'x', FederationSettings(allow_localhost=True))
    m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(fake.url, uid='nopkce')])
    try:
        import sajha.federation.oauth_user as ou
        real = ou._get_json

        def no_pkce(url, what, settings=None):
            d = real(url, what, settings)
            if d and 'code_challenge_methods_supported' in d:
                d['code_challenge_methods_supported'] = ['plain']
            return d
        monkeypatch.setattr(ou, '_get_json', no_pkce)
        with pytest.raises(OAuthUserError, match='PKCE'):
            vault.oauth.endpoints(m.get_config('nopkce'))
    finally:
        m.stop()


# ── two users, each as themselves ───────────────────────────────────

def test_two_users_sign_in_and_get_their_own_answers(tmp_path, monkeypatch, fake, vault):
    m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(fake.url)])
    try:
        assert wait_for(lambda: m.status('notes')['state'] == 'waiting_for_user')
        assert not reg.tools
        conn, _ = sign_in(vault, fake, 'notes', 'alice')
        assert conn.scopes == ['notes:read'] and conn.has_refresh_token and conn.expires_at
        assert wait_for(lambda: 'notes__whoami' in reg.tools)
        sign_in(vault, fake, 'notes', 'bob')
        tool = reg.tools['notes__whoami']
        for user in ('alice', 'bob'):
            fake.events.clear()
            with as_user(user):
                out = json.dumps(tool.execute_with_tracking({}))
            assert f'you are {user}-at-vendor' in out
            users = {d['user'] for d in fake.mcp_events()}
            assert users == {f'{user}-at-vendor'}, users       # every request carried that user's token
        st = vault.status_of(m.get_config('notes'), 'alice')
        assert st['status'] == 'connected' and st['mode'] == 'oauth_user' and st['scopes'] == ['notes:read']
        assert st['expires_at'] and st['refreshable'] and not st['write_granted'] and st['token_hint'] == ''
        assert m.status('notes')['auth_mode'] == 'oauth_user' and m.status('notes')['auth_note'] == ''
        with as_user('carol'), pytest.raises(ConnectedAccountRequired) as ei:
            tool.execute_with_tracking({})
        assert ei.value.reason == 'not_connected' and ei.value.local_path == '/account/server-connections/notes'
        assert any(e[0] == 'proxied_connection.connected' and e[3].get('mode') == 'oauth_user'
                   for e in vault.events)
    finally:
        m.stop()


def test_pkce_mismatch_and_bad_state_are_refused(tmp_path, monkeypatch, fake, vault):
    from sajha.accounts.service import FLOW_PREFIX
    m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(fake.url)])
    try:
        store = vault.oauth.service.store

        def wrong_verifier(back):
            rec = store.get(FLOW_PREFIX + back['state'])
            rec['v'] = 'x' * 64                  # not the verifier the challenge was made from
            store.set(FLOW_PREFIX + back['state'], rec, ttl=60)
        with pytest.raises(OAuthFlowError, match='refused the token request'):
            sign_in(vault, fake, 'notes', 'alice', tamper=wrong_verifier)
        assert any(w == 'pkce_refused' for w, _ in fake.events)
        with pytest.raises(OAuthFlowError, match='unknown or has expired'):
            sign_in(vault, fake, 'notes', 'alice', tamper=lambda b: b.update(state='forged'))
        with pytest.raises(OAuthFlowError, match='different browser'):
            sign_in(vault, fake, 'notes', 'alice', tamper=lambda b: b.update(nonce='another-browser'))
        cfg = m.get_config('notes')
        url = vault.oauth.start(cfg, 'alice', browser_nonce='n')
        state = dict(parse_qsl(urlsplit(url).query))['state']
        assert vault.oauth.flow_upstream(state) == 'notes'
        with pytest.raises(OAuthFlowError, match='different SAJHA user'):
            vault.oauth.complete(cfg, 'mallory', state=state, code='x', browser_nonce='n')
        assert vault.status_of(cfg, 'alice')['status'] == 'not_connected'
        assert any(e[0] == 'proxied_connection.state_rejected' for e in vault.events)
    finally:
        m.stop()


# ── refresh ─────────────────────────────────────────────────────────

def test_refresh_before_expiry_and_once_after_a_401(tmp_path, monkeypatch, fake, vault, skew):
    m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(fake.url)])
    try:
        sign_in(vault, fake, 'notes', 'alice')
        assert wait_for(lambda: 'notes__whoami' in reg.tools)
        tool = reg.tools['notes__whoami']
        cfg = m.get_config('notes')
        first = vault.vault.tokens(vault.vault.get('alice', 'upstream:notes'))['access_token']
        # 1. the vendor stops accepting the token early: one refresh, the call retried with the new one
        fake.events.clear()
        fake.expire('alice-at-vendor')
        with as_user('alice'):
            assert 'alice-at-vendor' in json.dumps(tool.execute_with_tracking({}))
        assert [d['grant'] for w, d in fake.events if w == 'token'] == ['refresh_token']
        second = vault.vault.tokens(vault.vault.get('alice', 'upstream:notes'))['access_token']
        assert second != first and first not in fake.access
        # 2. due within the skew: refreshed before the call, nothing refused on the way
        skew(10 ** 6)
        fake.events.clear()
        with as_user('alice'):
            assert 'alice-at-vendor' in json.dumps(tool.execute_with_tracking({}))
        assert [d['grant'] for w, d in fake.events if w == 'token'] == ['refresh_token']
        assert not [d for d in fake.mcp_events() if d['user'] is None]      # no 401 on the way
        assert any(e[0] == 'proxied_connection.refreshed' for e in vault.events)
        assert vault.status_of(cfg, 'alice')['status'] == 'connected'
    finally:
        m.stop()


def test_refresh_failure_marks_needs_reconnect(tmp_path, monkeypatch, fake, vault):
    m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(fake.url)])
    try:
        sign_in(vault, fake, 'notes', 'alice')
        sign_in(vault, fake, 'notes', 'bob')
        assert wait_for(lambda: 'notes__whoami' in reg.tools)
        tool = reg.tools['notes__whoami']
        fake.expire('alice-at-vendor')
        fake.fail_refresh = True
        with as_user('alice'), pytest.raises(ConnectedAccountRequired) as ei:
            tool.execute_with_tracking({})
        assert ei.value.reason == 'reauth_required'
        assert ei.value.connect_url.endswith('/account/server-connections/notes')
        st = vault.status_of(m.get_config('notes'), 'alice')
        assert st['status'] == 'needs_reconnect' and 'refresh refused' in st['last_error']
        with as_user('alice'), pytest.raises(ConnectedAccountRequired):
            tool.execute_with_tracking({})
        fake.fail_refresh = False
        with as_user('bob'):                                    # other users are unaffected
            assert 'bob-at-vendor' in json.dumps(tool.execute_with_tracking({}))
        sign_in(vault, fake, 'notes', 'alice')                   # signing in again repairs it
        with as_user('alice'):
            assert 'alice-at-vendor' in json.dumps(tool.execute_with_tracking({}))
    finally:
        m.stop()


# ── clients and scopes ──────────────────────────────────────────────

def test_operator_registered_client(tmp_path, monkeypatch, vault):
    from sajha.accounts.settings import base_url
    redirect = base_url() + '/account/server-connections/oauth/callback'
    f = fake_mod.FakeOAuthMCP(dcr=False, clients={'lab-app': {'secret': 'lab-secret-xyz',
                                                               'redirect_uris': [redirect]}}).start()
    monkeypatch.setenv('LAB_APP_SECRET', 'lab-secret-xyz')
    try:
        m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(f.url, client_id='lab-app',
                                                                client_secret_ref='env:LAB_APP_SECRET')])
        try:
            conn, q = sign_in(vault, f, 'notes', 'alice')
            assert q['client_id'] == 'lab-app' and conn.has_refresh_token
            assert not [1 for w, _ in f.events if w == 'register']
            assert wait_for(lambda: 'notes__whoami' in reg.tools)
            with as_user('alice'):
                assert 'alice-at-vendor' in json.dumps(reg.tools['notes__whoami'].execute_with_tracking({}))
            monkeypatch.setenv('LAB_APP_SECRET', 'wrong')        # the token endpoint authenticates the client
            vault.oauth.forget('notes')
            with pytest.raises(OAuthFlowError, match='invalid_client'):
                sign_in(vault, f, 'notes', 'bob')
        finally:
            m.stop()
    finally:
        f.stop()


def test_write_scopes_only_when_the_user_opts_in(tmp_path, monkeypatch, fake, vault):
    from sajha.federation.tool import FederatedToolError
    m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(fake.url, write_scopes=['notes:write'])])
    try:
        _, q = sign_in(vault, fake, 'notes', 'alice')
        assert q['scope'] == 'notes:read'
        assert wait_for(lambda: 'notes__add_note' in reg.tools)
        add = reg.tools['notes__add_note']
        with as_user('alice'), pytest.raises(FederatedToolError) as ei:
            add.execute_with_tracking({'text': 'hello'})
        assert 'HTTP 403' in str(ei.value) and 'needs notes:write' in str(ei.value)
        assert vault.status_of(m.get_config('notes'), 'alice')['status'] == 'connected'   # reads still work
        conn, q = sign_in(vault, fake, 'notes', 'alice', write=True)
        assert q['scope'] == 'notes:read notes:write' and 'notes:write' in conn.scopes
        with as_user('alice'):
            assert 'added for alice-at-vendor' in json.dumps(add.execute_with_tracking({'text': 'hello'}))
        assert vault.status_of(m.get_config('notes'), 'alice')['write_granted'] is True
        _, q = sign_in(vault, fake, 'notes', 'alice')            # signing in again without it drops it
        assert q['scope'] == 'notes:read'
        assert vault.status_of(m.get_config('notes'), 'alice')['write_granted'] is False
    finally:
        m.stop()


# ── revocation ──────────────────────────────────────────────────────

def test_disconnect_and_sign_out_everywhere_revoke_at_the_vendor(tmp_path, monkeypatch, fake, vault):
    m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(fake.url)])
    try:
        sign_in(vault, fake, 'notes', 'alice')
        sign_in(vault, fake, 'notes', 'frank')
        assert vault.remove('notes', 'alice', actor='alice')
        assert fake.revoked == ['alice-at-vendor']
        assert not [r for r in fake.access.values() if r['user'] == 'alice-at-vendor']
        assert any(e[0] == 'proxied_connection.disconnected' and e[3].get('revoked_at_vendor') is True
                   for e in vault.events)
        from sajha.auth.revocation import end_all_sessions

        class _DB:
            def commit(self):
                pass

            def add(self, *_a):
                pass

        class _U:
            user_id, token_version = 'frank', 0
        end_all_sessions(_DB(), _U(), 'frank', 'sign_out_everywhere')
        assert 'frank-at-vendor' in fake.revoked
        assert vault.status_of(m.get_config('notes'), 'frank')['status'] == 'not_connected'
        # the vendor down: the token is still forgotten here
        sign_in(vault, fake, 'notes', 'gina')
        fake.stop()
        assert vault.remove('notes', 'gina', actor='admin')
        assert vault.status_of(m.get_config('notes'), 'gina')['status'] == 'not_connected'
    finally:
        m.stop()


@pytest.fixture(scope='module')
def app_client():
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        yield c


def _bearer():
    from sajha.auth.jwt_handler import create_access_token
    return {'Authorization': 'Bearer ' + create_access_token('admin', ['admin'])}


def _db_user(uid):
    from sajha.auth.password import hash_password
    from sajha.db.dao import RoleDAO, UserDAO
    from sajha.db.engine import get_db_session
    from sajha.db.models import User
    db = get_db_session()
    try:
        user = User(user_id=uid, user_name=uid, email='', password_hash=hash_password('Passw0rd!x'), enabled=True)
        user.roles.append(RoleDAO(db).get_or_create('user'))
        UserDAO(db).create(user)
    finally:
        db.close()


def test_disable_revokes_by_admin_route_and_by_users_file_sync(tmp_path, monkeypatch, fake, vault, app_client):
    """Both modes: a user disabled by an administrator or in the users file loses every proxied-server token
    (an OAuth one revoked at the vendor too)."""
    from sajha.auth.users_file import UsersFile, sync_to_database
    from sajha.db.engine import get_db_session
    m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(fake.url),
                                                 {'id': 'pat', 'url': 'https://pat.example/mcp',
                                                  'protocol': '2026-07-28', 'enabled': False,
                                                  'auth': {'type': 'token_user'}}])
    pat_cfg = m.get_config('pat')
    try:
        uid = f'oau_{uuid.uuid4().hex[:8]}'
        _db_user(uid)
        sign_in(vault, fake, 'notes', uid)
        vault.save(pat_cfg, uid, 'vt_personal_token_0123456789')
        r = app_client.post(f'/api/admin/users/{uid}/disable', headers=_bearer())
        assert r.status_code == 200
        assert vault.status_of(m.get_config('notes'), uid)['status'] == 'not_connected'
        assert vault.status_of(pat_cfg, uid)['status'] == 'not_connected'
        assert f'{uid}-at-vendor' in fake.revoked
        # the users file
        uf_user = f'ouf_{uuid.uuid4().hex[:8]}'
        store = UsersFile(tmp_path / 'users.json')
        store.upsert({'user_id': uf_user, 'password': 'uf-pass-123', 'roles': ['user'], 'enabled': True})
        db = get_db_session()
        try:
            assert sync_to_database(db, store)[0] == 1
        finally:
            db.close()
        sign_in(vault, fake, 'notes', uf_user)
        vault.save(pat_cfg, uf_user, 'vt_personal_token_0123456789')
        db = get_db_session()
        try:
            sync_to_database(db, store)                         # still enabled: nothing happens
        finally:
            db.close()
        assert vault.status_of(pat_cfg, uf_user)['status'] == 'connected'
        store.upsert({'user_id': uf_user, 'password': 'uf-pass-123', 'roles': ['user'], 'enabled': False})
        db = get_db_session()
        try:
            sync_to_database(db, store)
        finally:
            db.close()
        assert vault.status_of(m.get_config('notes'), uf_user)['status'] == 'not_connected'
        assert vault.status_of(pat_cfg, uf_user)['status'] == 'not_connected'
        assert f'{uf_user}-at-vendor' in fake.revoked
        assert any(e[0] == 'proxied_connection.disconnected' and e[1] == 'users_file' for e in vault.events)
    finally:
        m.stop()


# ── secrecy ─────────────────────────────────────────────────────────

def test_tokens_never_appear_in_logs_audit_status_or_errors(tmp_path, monkeypatch, fake, vault, caplog):
    from sajha.federation.tool import FederatedToolError
    caplog.set_level(logging.DEBUG)
    m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(fake.url, write_scopes=['notes:write'])])
    texts, issued = [], set()
    try:
        sign_in(vault, fake, 'notes', 'alice')
        issued.update(secrets_of(fake))
        assert wait_for(lambda: 'notes__whoami' in reg.tools)
        with as_user('alice'):
            texts.append(json.dumps(reg.tools['notes__whoami'].execute_with_tracking({})))
            with pytest.raises(FederatedToolError) as e:
                reg.tools['notes__add_note'].execute_with_tracking({'text': 'x'})
            texts.append(str(e.value))
        fake.expire()
        with as_user('alice'):
            texts.append(json.dumps(reg.tools['notes__whoami'].execute_with_tracking({})))   # refreshed
        issued.update(secrets_of(fake))
        fake.expire()
        fake.fail_refresh = True
        with as_user('alice'), pytest.raises(ConnectedAccountRequired) as e2:
            reg.tools['notes__whoami'].execute_with_tracking({})
        texts.append(str(e2.value))
        texts.append(json.dumps(m.status('notes'), default=str))
        texts.append(json.dumps(vault.all_connections(), default=str))
        texts.append(json.dumps(vault.status_of(m.get_config('notes'), 'alice'), default=str))
        texts.append(json.dumps(vault.events, default=str))
        vault.remove('notes', 'alice')
        texts.append(json.dumps(vault.events, default=str))
    finally:
        m.stop()
    texts.append(caplog.text)
    codes = [d for w, d in fake.events if w == 'authorize']
    assert issued and codes
    for t in texts:
        for s in issued:
            assert s not in t, (s[:8], t[:300])
    from sqlalchemy import text
    with vault.vault.engine.connect() as c:
        rows = ' '.join(str(r) for r in c.execute(text('SELECT * FROM connected_accounts')).all())
    for s in issued:
        assert s not in rows


# ── SAJHA Net and session-based upstreams ───────────────────────────

def test_sajhanet_relays_the_connect_request_for_an_oauth_upstream(tmp_path, vault, monkeypatch):
    from datetime import timedelta
    from sajha.accounts.vault import utcnow
    from sajha.core.mcp_mrtr import InputRequired
    from sajha.core.mcp_tool_context import ModernToolContext
    from sajha.federation.user_tokens import get_tokens
    from sajha.observability.caller import current
    from tests.net import test_net_routing_integration as tri
    from tests.net.test_net_routing_integration import Echo, make, node, settle
    from tests.net.test_net_streaming import StreamConnector, call, quick, stream_app_for
    net = 'acme-net'
    cfg = UpstreamConfig.from_dict(oauth_user('https://vendor.example/mcp', uid='gh'))
    seen_users = []

    class NeedsSignIn(Echo):
        def execute(self, arguments):
            seen_users.append(current().user_id)
            token = get_tokens().resolve(cfg, current().user_id, tool=self.name)
            return f'ran with an access token of {len(token)} characters'

    monkeypatch.setattr(tri, 'app_for', stream_app_for)
    conn = StreamConnector()
    a = make(tmp_path, 'risk-eu', conn, [Echo('var_calc', owner='risk-eu')], founder=True)
    a.start(run_agents=False)
    a.ca_init(net)
    assert node(a).try_join()
    b = make(tmp_path, 'cust-na', conn, [NeedsSignIn('gh_tool', owner='cust-na')])
    b.start(run_agents=False)
    b.enroll(net, 'https://risk-eu.test', a.ca_token(net, 'cust-na')['token'], by='test')
    assert node(b).try_join()
    access = 'oauth_access_CANARY9f3_' + 'a' * 20
    try:
        settle([a, b], 5)
        quick(a, progress_min_interval_ms=0)
        quick(b, progress_min_interval_ms=0)
        name = f'{net}__cust-na__gh_tool'
        with pytest.raises(InputRequired) as ir:
            call(a, name, {'x': 1}, ModernToolContext())
        key = 'sajha.connect.upstream:gh'
        req = ir.value.requests[key]
        assert req['method'] == 'elicitation/create' and req['params']['mode'] == 'url'
        assert req['params']['url'].endswith('/account/server-connections/gh')
        mapped = seen_users[-1]
        vault.vault.save(mapped, 'upstream:gh', {'access_token': access, 'refresh_token': 'r' * 30},
                         scopes=['repo:read'], expires_at=utcnow() + timedelta(hours=1))    # signed in at the host
        r = call(a, name, {'x': 1}, ModernToolContext(input_responses={key: {'action': 'accept'}},
                                                      state=ir.value.state))
        assert 'ran with an access token of' in json.dumps(r), r
        assert 'CANARY9f3' not in json.dumps([str(x) for x in conn.mcp])      # the token never left the host
    finally:
        a.stop()
        b.stop()


def test_session_based_upstream_with_oauth(tmp_path, monkeypatch, fake, vault):
    m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(fake.url, protocol='legacy')])
    try:
        sign_in(vault, fake, 'notes', 'alice')
        sign_in(vault, fake, 'notes', 'bob')
        assert wait_for(lambda: 'notes__whoami' in reg.tools)
        tool = reg.tools['notes__whoami']
        fake.events.clear()
        for user in ('alice', 'bob', 'alice'):
            with as_user(user):
                assert f'you are {user}-at-vendor' in json.dumps(tool.execute_with_tracking({}))
        assert m.user_sessions('notes') == ['alice', 'bob']
        inits = [d['user'] for d in fake.mcp_events('initialize')]
        assert sorted(inits) == ['alice-at-vendor', 'bob-at-vendor']
        sessions = {}
        for d in fake.mcp_events('tools/call'):
            sessions.setdefault(d['session'], set()).add(d['user'])
        assert len(sessions) == 2 and all(len(v) == 1 for v in sessions.values())
        fake.expire('alice-at-vendor')                          # refused in her session: refresh, new session
        fake.events.clear()
        with as_user('alice'):
            assert 'you are alice-at-vendor' in json.dumps(tool.execute_with_tracking({}))
        assert [d['grant'] for w, d in fake.events if w == 'token'] == ['refresh_token']
        assert [d['user'] for d in fake.mcp_events('initialize')] == ['alice-at-vendor']
        assert 'alice' in m.user_sessions('notes')
    finally:
        m.stop()


# ── the pages ───────────────────────────────────────────────────────

def test_connect_page_and_callback_end_to_end(tmp_path, monkeypatch, fake, vault, app_client):
    c = app_client
    m, reg = manager_for(tmp_path, monkeypatch, [oauth_user(fake.url, uid='notesx', write_scopes=['notes:write'],
                                                            help_url='https://vendor.example/about')])
    try:
        c.cookies.clear()
        login = c.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
        cookies = dict(login.cookies)
        page = c.get('/account/server-connections', cookies=cookies)
        assert page.status_code == 200 and 'Lab notes' in page.text and 'Not connected' in page.text
        cp = c.get('/account/server-connections/notesx', cookies=cookies)
        assert cp.status_code == 200 and 'Connect with Lab notes' in cp.text and 'notes:write' in cp.text
        assert 'type="password"' not in cp.text
        csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', cp.text).group(1)
        assert c.post('/account/server-connections/notesx/oauth/start', data={'csrf': 'nope'}, cookies=cookies,
                      follow_redirects=False).status_code == 403
        go = c.post('/account/server-connections/notesx/oauth/start', data={'csrf': csrf, 'write': '1'},
                    cookies=cookies, follow_redirects=False)
        assert go.status_code == 303 and go.headers['location'].startswith(fake.issuer + '/authorize?')
        flow = go.cookies.get('sajha_upstream_flow')
        assert flow
        q = dict(parse_qsl(urlsplit(go.headers['location']).query))
        assert q['redirect_uri'] == 'http://testserver/account/server-connections/oauth/callback'
        assert q['scope'] == 'notes:read notes:write'
        r = httpx.post(fake.issuer + '/authorize', data={**q, 'user': 'admin-at-vendor', 'decision': 'allow'},
                       follow_redirects=False)
        back = urlsplit(r.headers['location'])
        # without the browser's flow cookie: refused, nothing saved
        c.cookies.clear()
        bad = c.get(back.path + '?' + back.query, cookies=cookies, follow_redirects=False)
        assert bad.status_code == 303 and 'different+browser' in bad.headers['location']
        go = c.post('/account/server-connections/notesx/oauth/start', data={'csrf': csrf, 'write': '1'},
                    cookies=cookies, follow_redirects=False)
        q = dict(parse_qsl(urlsplit(go.headers['location']).query))
        r = httpx.post(fake.issuer + '/authorize', data={**q, 'user': 'admin-at-vendor', 'decision': 'allow'},
                       follow_redirects=False)
        back = urlsplit(r.headers['location'])
        c.cookies.clear()
        ok = c.get(back.path + '?' + back.query, cookies={**cookies, 'sajha_upstream_flow':
                                                          go.cookies.get('sajha_upstream_flow')},
                   follow_redirects=False)
        assert ok.status_code == 303 and ok.headers['location'] == '/account/server-connections?saved=notesx'
        page = c.get('/account/server-connections?saved=notesx', cookies=cookies)
        assert 'Connected to Lab notes' in page.text and 'notes:write' in page.text and 'changes allowed' in page.text
        admin_page = c.get('/admin/server-connections', cookies=cookies)
        assert admin_page.status_code == 200 and 'OAuth' in admin_page.text and 'renewable' in admin_page.text
        # denied at the vendor: shown plainly
        go = c.post('/account/server-connections/notesx/oauth/start', data={'csrf': csrf}, cookies=cookies,
                    follow_redirects=False)
        q = dict(parse_qsl(urlsplit(go.headers['location']).query))
        r = httpx.post(fake.issuer + '/authorize', data={**q, 'user': 'x', 'decision': 'deny'},
                       follow_redirects=False)
        back = urlsplit(r.headers['location'])
        c.cookies.clear()
        denied = c.get(back.path + '?' + back.query, cookies={**cookies, 'sajha_upstream_flow':
                                                              go.cookies.get('sajha_upstream_flow')},
                       follow_redirects=False)
        assert 'did+not+grant+access' in denied.headers['location']
        stale = c.get('/account/server-connections/oauth/callback?state=nope&code=x', cookies=cookies,
                      follow_redirects=False)
        assert 'unknown+or+has+expired' in stale.headers['location']
        api = c.get('/api/accounts/server-connections', cookies=cookies).json()
        assert api['connections'][0]['mode'] == 'oauth_user' and api['connections'][0]['scopes']
        for s in secrets_of(fake):
            assert s not in json.dumps(api) and s not in page.text and s not in admin_page.text
        out = c.post('/account/server-connections/notesx/remove', data={'csrf': csrf}, cookies=cookies,
                     follow_redirects=False)
        assert out.status_code == 303 and 'admin-at-vendor' in fake.revoked
    finally:
        c.cookies.clear()
        m.stop()
