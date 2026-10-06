"""
Connected accounts (sajha/accounts): per-user OAuth links, the token vault, refresh,
revocation, tool binding, the "connect your account" answers on every front end, and
per-user token passthrough to federated upstreams.

A fake OAuth 2.0 provider runs in process (an httpx transport): it issues codes bound to
the PKCE challenge and the redirect URI, checks the client and the verifier at the token
endpoint, rotates refresh tokens, revokes, and serves the provider APIs the example tools
call (GitHub, Slack, Google Drive, Microsoft Graph), accepting only tokens it issued.

Design: docs/architecture/Connected Accounts.md
"""

import base64
import hashlib
import json
import threading
import time
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import create_engine, text

from sajha.accounts import http as ahttp
from sajha.accounts.errors import ConnectedAccountRequired, OAuthFlowError, VaultError
from sajha.accounts.providers import ProviderConfigError, ProviderRegistry, build_provider, set_registry
from sajha.accounts.service import ConnectedAccountsService, pkce_challenge, set_service
from sajha.accounts.settings import AccountsSettings, set_accounts_settings
from sajha.accounts.vault import LocalKeyProvider, TokenVault, set_vault, utcnow
from sajha.core.mcp_mrtr import InputRequired
from sajha.core.state.memory import MemoryStateStore
from sajha.observability.caller import Caller, reset, set_caller

AUTH = 'https://auth.fake.test'
SECRET = 'fake-client-secret-value-0123456789'
KEY1 = 'test-vault-key-one-' + 'x' * 32
KEY2 = 'test-vault-key-two-' + 'y' * 32


# ── the fake provider ───────────────────────────────────────────────

class FakeProvider:
    """An OAuth 2.0 authorization server plus the provider APIs, in process."""

    def __init__(self):
        self.codes = {}            # code -> grant
        self.access = {}           # access token -> (user, scopes)
        self.refresh = {}          # refresh token -> (user, scopes)
        self.n = 0
        self.expires_in = 3600
        self.issue_refresh = True
        self.refresh_mode = 'ok'   # ok | invalid_grant | down
        self.token_requests = []
        self.revoked = []
        self.api_calls = []        # (method, url, user)
        self.reject_next_api = 0   # answer 401 this many times
        self.lock = threading.Lock()

    # the browser leg: the user approves on the provider's page
    def approve(self, authorize_url, login='octo-alice', deny=False, scope_override=None):
        q = {k: v[0] for k, v in parse_qs(urlsplit(authorize_url).query).items()}
        assert q['response_type'] == 'code' and q['client_id'] == 'cid'
        if deny:
            return {'state': q['state'], 'error': 'access_denied'}
        code = f'code-{self.n}-{login}'
        self.n += 1
        scope = scope_override if scope_override is not None else q.get('scope') or q.get('user_scope') or ''
        self.codes[code] = {'redirect_uri': q['redirect_uri'], 'challenge': q.get('code_challenge'),
                            'method': q.get('code_challenge_method'), 'login': login, 'scope': scope}
        return {'state': q['state'], 'code': code}

    def _issue(self, login, scope):
        with self.lock:
            self.n += 1
            at, rt = f'at-{login}-{self.n}', f'rt-{login}-{self.n}'
        self.access[at] = (login, scope)
        body = {'access_token': at, 'token_type': 'bearer', 'scope': scope.replace(' ', ',')}
        if self.expires_in is not None:
            body['expires_in'] = self.expires_in
        if self.issue_refresh:
            self.refresh[rt] = (login, scope)
            body['refresh_token'] = rt
        return body

    def _user(self, request):
        h = request.headers.get('authorization', '')
        tok = h[7:] if h.startswith('Bearer ') else ''
        return self.access.get(tok, (None, ''))[0], tok

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        host = request.url.host
        path = request.url.path
        if host == 'auth.fake.test' and path == '/token':
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(dict(form))
            if form.get('client_id') != 'cid' or form.get('client_secret') != SECRET:
                return httpx.Response(401, json={'error': 'invalid_client'})
            if form['grant_type'] == 'authorization_code':
                grant = self.codes.pop(form.get('code'), None)          # single use
                if grant is None:
                    return httpx.Response(400, json={'error': 'invalid_grant'})
                if form.get('redirect_uri') != grant['redirect_uri']:
                    return httpx.Response(400, json={'error': 'invalid_grant', 'error_description': 'redirect_uri'})
                if grant['challenge']:
                    v = form.get('code_verifier', '')
                    calc = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b'=').decode()
                    if grant['method'] != 'S256' or calc != grant['challenge']:
                        return httpx.Response(400, json={'error': 'invalid_grant', 'error_description': 'pkce'})
                return httpx.Response(200, json=self._issue(grant['login'], grant['scope']))
            if form['grant_type'] == 'refresh_token':
                if self.refresh_mode == 'down':
                    return httpx.Response(503, text='maintenance')
                if self.refresh_mode == 'invalid_grant':
                    return httpx.Response(400, json={'error': 'invalid_grant'})
                found = self.refresh.pop(form.get('refresh_token'), None)    # rotation: old one dies
                if found is None:
                    return httpx.Response(400, json={'error': 'invalid_grant'})
                return httpx.Response(200, json=self._issue(*found))
        if host == 'auth.fake.test' and path == '/revoke':
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.revoked.append(form.get('token'))
            self.refresh.pop(form.get('token'), None)
            return httpx.Response(200)
        user, tok = self._user(request)
        self.api_calls.append((request.method, url, user))
        if self.reject_next_api:
            self.reject_next_api -= 1
            return httpx.Response(401, json={'message': 'Bad credentials'})
        if user is None:
            if host == 'slack.com':
                return httpx.Response(200, json={'ok': False, 'error': 'invalid_auth'})
            return httpx.Response(401, json={'message': 'Bad credentials'})
        if host == 'api.github.com':
            if path == '/user':
                return httpx.Response(200, json={'login': user, 'id': 4242})
            if path == '/user/repos':
                return httpx.Response(200, json=[{'full_name': f'{user}/hello', 'private': True, 'html_url': 'u',
                                                  'stargazers_count': 3, 'open_issues_count': 1}])
            if path.endswith('/issues') and request.method == 'POST':
                body = json.loads(request.content)
                return httpx.Response(201, json={'number': 7, 'html_url': 'https://github.com/x/y/issues/7',
                                                 'title': body['title'], 'state': 'open', 'user': {'login': user}})
        if host == 'slack.com' and path == '/api/chat.postMessage':
            body = json.loads(request.content)
            return httpx.Response(200, json={'ok': True, 'channel': body['channel'], 'ts': '1.2',
                                             'message': {'text': body['text']}})
        if host == 'slack.com' and path == '/api/auth.test':
            return httpx.Response(200, json={'ok': True, 'user': user, 'user_id': 'U1'})
        if host == 'www.googleapis.com' and path == '/drive/v3/files':
            return httpx.Response(200, json={'files': [{'id': 'f1', 'name': 'Budget', 'mimeType': 'x',
                                                        'owners': [{'displayName': user}]}]})
        if host == 'openidconnect.googleapis.com':
            return httpx.Response(200, json={'email': f'{user}@example.com', 'sub': 's1'})
        if host == 'graph.microsoft.com' and path == '/v1.0/me/calendarView':
            return httpx.Response(200, json={'value': [{'subject': 'Standup', 'start': {'dateTime': 'a'},
                                                        'end': {'dateTime': 'b'}}]})
        if host == 'graph.microsoft.com' and path == '/v1.0/me':
            return httpx.Response(200, json={'userPrincipalName': f'{user}@contoso.com', 'id': 'm1'})
        return httpx.Response(404, json={'message': 'not found'})


def _fake_endpoints(pid):
    return {'client_id': 'cid', 'client_secret_ref': 'env:FAKE_PROVIDER_SECRET',
            'authorize_url': f'{AUTH}/authorize', 'token_url': f'{AUTH}/token',
            'revoke_url': f'{AUTH}/revoke', 'revoke_style': 'rfc7009', 'token_response_path': ''}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A configured service over a temporary vault, a memory state store and the fake provider."""
    monkeypatch.setenv('FAKE_PROVIDER_SECRET', SECRET)
    fake = FakeProvider()
    ahttp.set_transport(httpx.MockTransport(fake.handler))
    settings = AccountsSettings(public_url='https://sajha.test')
    set_accounts_settings(settings)
    raw = {pid: _fake_endpoints(pid) for pid in ('github', 'slack', 'google', 'microsoft')}
    raw['slack']['scope_param'] = 'scope'
    registry = ProviderRegistry.load(raw=raw, use_env=False)
    set_registry(registry)
    engine = create_engine(f'sqlite:///{tmp_path / "vault.db"}')
    vault = TokenVault(engine=engine, key_provider=LocalKeyProvider(KEY1))
    set_vault(vault)
    store = MemoryStateStore('t:')
    svc = ConnectedAccountsService(registry, vault, store)
    events = []
    monkeypatch.setattr(ConnectedAccountsService, 'audit',
                        staticmethod(lambda action, user_id, provider, ip=None, **d: events.append(
                            (action, user_id, provider, d))))
    set_service(svc)

    class Env:
        pass
    e = Env()
    e.fake, e.svc, e.vault, e.engine, e.store, e.events, e.registry = fake, svc, vault, engine, store, events, registry
    yield e
    ahttp.set_transport(None)
    set_service(None)
    set_vault(None)
    set_registry(None)
    set_accounts_settings(None)


def link(e, user='alice', pid='github', login=None, scopes=None):
    """The whole dance: start -> provider approval -> callback."""
    url = e.svc.start(user, pid, browser_nonce='nonce-' + user, scopes=scopes)
    back = e.fake.approve(url, login=login or f'octo-{user}')
    return e.svc.complete(user, pid, state=back['state'], code=back.get('code', ''),
                          error=back.get('error', ''), browser_nonce='nonce-' + user)['connection']


class as_user:
    def __init__(self, uid):
        self.uid = uid

    def __enter__(self):
        self.t = set_caller(Caller(self.uid))

    def __exit__(self, *a):
        reset(self.t)


def load_tool(name):
    import importlib
    cfg = json.load(open(f'config/tools/{name}.json'))
    mod, cls = cfg['implementation'].rsplit('.', 1)
    return getattr(importlib.import_module(mod), cls)(cfg)


# ── the authorization-code flow ─────────────────────────────────────

def test_full_oauth_dance_with_pkce(env):
    url = env.svc.start('alice', 'github', browser_nonce='n1')
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith(f'{AUTH}/authorize?')
    assert q['code_challenge_method'] == 'S256' and len(q['code_challenge']) == 43
    assert q['redirect_uri'] == 'https://sajha.test/account/connections/github/callback'
    assert set(q['scope'].split()) == {'read:user', 'repo'} and len(q['state']) >= 40
    back = env.fake.approve(url)
    out = env.svc.complete('alice', 'github', state=back['state'], code=back['code'], browser_nonce='n1')
    conn = out['connection']
    assert conn.account_login == 'octo-alice' and conn.status == 'active' and conn.has_refresh_token
    assert set(conn.scopes) == {'read:user', 'repo'}
    sent = env.fake.token_requests[-1]
    assert sent['redirect_uri'] == q['redirect_uri'] and pkce_challenge(sent['code_verifier']) == q['code_challenge']
    assert ('connected_account_linked', 'alice', 'github') == env.events[-1][:3]
    assert 'at-' not in json.dumps(env.events, default=str)            # no token in the audit trail


def test_state_is_single_use_bound_to_user_and_browser(env):
    url = env.svc.start('alice', 'github', browser_nonce='n1')
    back = env.fake.approve(url)
    with pytest.raises(OAuthFlowError, match='different SAJHA user'):
        env.svc.complete('mallory', 'github', state=back['state'], code=back['code'], browser_nonce='n1')
    with pytest.raises(OAuthFlowError, match='unknown or has expired'):      # popped by the failed attempt
        env.svc.complete('alice', 'github', state=back['state'], code=back['code'], browser_nonce='n1')
    url = env.svc.start('alice', 'github', browser_nonce='n2')
    back = env.fake.approve(url)
    with pytest.raises(OAuthFlowError, match='different browser'):
        env.svc.complete('alice', 'github', state=back['state'], code=back['code'], browser_nonce='other')
    with pytest.raises(OAuthFlowError, match='unknown or has expired'):
        env.svc.complete('alice', 'github', state='forged', code='x', browser_nonce='n2')
    assert {e[0] for e in env.events} == {'connected_account_state_rejected'}
    assert env.vault.get('alice', 'github') is None


def test_provider_denial_and_bad_code(env):
    url = env.svc.start('alice', 'github', browser_nonce='n1')
    back = env.fake.approve(url, deny=True)
    with pytest.raises(OAuthFlowError, match='access_denied'):
        env.svc.complete('alice', 'github', state=back['state'], error=back['error'], browser_nonce='n1')
    url = env.svc.start('alice', 'github', browser_nonce='n1')
    back = env.fake.approve(url)
    with pytest.raises(OAuthFlowError, match='invalid_grant'):
        env.svc.complete('alice', 'github', state=back['state'], code='not-the-code', browser_nonce='n1')
    assert [e[0] for e in env.events] == ['connected_account_link_failed', 'connected_account_link_failed']


def test_pkce_verifier_and_redirect_uri_are_checked_by_the_provider(env):
    url = env.svc.start('alice', 'github', browser_nonce='n1')
    back = env.fake.approve(url)
    rec = env.store.get('accounts:flow:' + back['state'])
    rec['v'] = 'a-different-verifier-' + 'z' * 40
    env.store.set('accounts:flow:' + back['state'], rec, ttl=60)
    with pytest.raises(OAuthFlowError, match='invalid_grant'):
        env.svc.complete('alice', 'github', state=back['state'], code=back['code'], browser_nonce='n1')
    url = env.svc.start('alice', 'github', browser_nonce='n1')
    back = env.fake.approve(url)
    rec = env.store.get('accounts:flow:' + back['state'])
    rec['r'] = 'https://evil.test/callback'
    env.store.set('accounts:flow:' + back['state'], rec, ttl=60)
    with pytest.raises(OAuthFlowError, match='invalid_grant'):
        env.svc.complete('alice', 'github', state=back['state'], code=back['code'], browser_nonce='n1')


def test_slack_user_token_and_scope_param(env, monkeypatch):
    p = build_provider('slack', {k: v for k, v in _fake_endpoints('slack').items() if k != 'token_response_path'},
                       use_env=False)
    assert p.scope_param == 'user_scope' and p.token_response_path == 'authed_user' and p.scope_separator == ','
    q = parse_qs(urlsplit(ConnectedAccountsService(ProviderRegistry({'slack': p}), env.vault, env.store)
                          .start('alice', 'slack', browser_nonce='n')).query)
    assert q['user_scope'] == ['chat:write,channels:read'] and 'scope' not in q and 'code_challenge' not in q


def test_provider_config_rules():
    with pytest.raises(ProviderConfigError, match='client_secret_ref'):
        build_provider('github', {'client_id': 'x', 'client_secret': 'inline'}, use_env=False)
    with pytest.raises(ProviderConfigError, match='reference'):
        build_provider('github', {'client_id': 'x', 'client_secret_ref': 'plaintext'}, use_env=False)
    with pytest.raises(ProviderConfigError, match='https'):
        build_provider('custom', {'client_id': 'x', 'authorize_url': 'http://evil.test/a',
                                  'token_url': 'https://t', 'api_hosts': ['a']}, use_env=False)
    with pytest.raises(ProviderConfigError, match='api_hosts'):
        build_provider('custom', {'client_id': 'x', 'authorize_url': 'https://a/a', 'token_url': 'https://a/t',
                                  'client_secret_ref': 'env:X'}, use_env=False)
    reg = ProviderRegistry.load(raw={}, use_env=False)
    assert {p.id for p in reg.all()} >= {'github', 'slack', 'google', 'microsoft', 'atlassian', 'notion'}
    assert reg.configured() == []                                  # nothing without a client id
    ms = build_provider('microsoft', {'client_id': 'x', 'client_secret_ref': 'env:X', 'tenant': 'contoso'},
                        use_env=False)
    assert ms.url('authorize_url') == 'https://login.microsoftonline.com/contoso/oauth2/v2.0/authorize'
    assert ms.missing_scopes(['https://graph.microsoft.com/calendars.read'], ['Calendars.Read']) == []


def test_env_overrides_a_provider_field(monkeypatch):
    monkeypatch.setenv('SAJHA_ACCOUNTS_PROVIDERS_GITHUB_CLIENT_ID', 'from-env')
    monkeypatch.setenv('SAJHA_ACCOUNTS_PROVIDERS_GITHUB_CLIENT_SECRET_REF', 'env:GH_SECRET')
    p = ProviderRegistry.load(raw={}).get('github')
    assert p.client_id == 'from-env' and p.configured


# ── the vault ───────────────────────────────────────────────────────

def test_database_holds_ciphertext_only(env):
    link(env)
    token = env.vault.tokens(env.vault.get('alice', 'github'))
    with env.engine.connect() as c:
        row = dict(c.execute(text('SELECT * FROM connected_accounts')).mappings().one())
    blob = json.dumps(row, default=str)
    assert token['access_token'] not in blob and token['refresh_token'] not in blob
    assert row['token_ciphertext'].startswith('v1:') and row['key_id'].startswith('k')
    assert row['account_login'] == 'octo-alice'


def test_ciphertext_is_bound_to_its_user_and_provider(env):
    link(env, 'alice')
    link(env, 'bob')
    with env.engine.begin() as c:
        ct = c.execute(text("SELECT token_ciphertext FROM connected_accounts WHERE user_id='alice'")).scalar()
        c.execute(text("UPDATE connected_accounts SET token_ciphertext=:ct WHERE user_id='bob'"), {'ct': ct})
    with pytest.raises(VaultError, match='decrypt'):
        env.vault.tokens(env.vault.get('bob', 'github'))


def test_key_rotation(env):
    link(env)
    old_kid = env.vault.get('alice', 'github').key_id
    v2 = TokenVault(engine=env.engine, key_provider=LocalKeyProvider(KEY2, [KEY1]))
    assert v2.key_usage() == {old_kid: 1}
    assert v2.rotate() == {'rotated': 1, 'failed': 0, 'current': 0}
    new_kid = v2.get('alice', 'github').key_id
    assert new_kid != old_kid and v2.tokens(v2.get('alice', 'github'))['access_token'].startswith('at-')
    with pytest.raises(VaultError, match='no vault key'):
        env.vault.tokens(env.vault.get('alice', 'github'))          # the old key alone cannot read it now
    v3 = TokenVault(engine=env.engine, key_provider=LocalKeyProvider(KEY1, [KEY2]))
    conn = v3.get('alice', 'github')
    v3.tokens(conn)                                                 # read with an old key re-encrypts lazily
    assert v3.get('alice', 'github').key_id == v3.keys.current()[0]


def test_key_provider_hook(env, monkeypatch):
    import sys
    import types
    mod = types.ModuleType('fake_kms_mod')

    class KP:
        def current(self):
            return 'kms1', b'k' * 32

        def lookup(self, kid):
            return b'k' * 32 if kid == 'kms1' else None
    mod.factory = KP
    monkeypatch.setitem(sys.modules, 'fake_kms_mod', mod)
    from sajha.accounts.vault import build_key_provider
    kp = build_key_provider(AccountsSettings(vault_key_provider='fake_kms_mod:factory'))
    v = TokenVault(engine=env.engine, key_provider=kp)
    v.save('u', 'github', {'access_token': 'secret-at'}, scopes=[], expires_at=None)
    assert v.get('u', 'github').key_id == 'kms1' and v.tokens(v.get('u', 'github'))['access_token'] == 'secret-at'


# ── tokens for tools: refresh, scopes, isolation ───────────────────

def test_refresh_on_expiry_rotates_and_audits(env):
    env.fake.expires_in = 60                        # inside the 120 s skew: refresh before use
    link(env)
    before = env.vault.tokens(env.vault.get('alice', 'github'))
    env.fake.expires_in = 3600
    tok = env.svc.resolve('alice', 'github')
    assert tok.access_token != before['access_token'] and tok.access_token in env.fake.access
    after = env.vault.tokens(env.vault.get('alice', 'github'))
    assert after['refresh_token'] != before['refresh_token'] and before['refresh_token'] not in env.fake.refresh
    assert env.events[-1][0] == 'connected_account_refreshed'
    assert env.svc.resolve('alice', 'github').access_token == tok.access_token     # no second refresh


def test_refused_refresh_marks_the_link_for_reconnect(env):
    env.fake.expires_in = 60
    link(env)
    env.fake.refresh_mode = 'invalid_grant'
    with pytest.raises(ConnectedAccountRequired) as ei:
        env.svc.resolve('alice', 'github')
    assert ei.value.reason == 'reauth_required' and 'connect=github' in ei.value.connect_url
    conn = env.vault.get('alice', 'github')
    assert conn.status == 'reauth_required' and 'invalid_grant' in conn.last_error
    assert env.events[-1][0] == 'connected_account_refresh_failed'
    with pytest.raises(ConnectedAccountRequired):                   # stays failed without a new dance
        env.svc.resolve('alice', 'github')
    link(env)                                                       # reconnecting clears it
    assert env.vault.get('alice', 'github').status == 'active'


def test_provider_outage_keeps_the_link_and_the_old_token(env):
    env.fake.expires_in = 60
    link(env)
    old = env.vault.tokens(env.vault.get('alice', 'github'))['access_token']
    env.fake.refresh_mode = 'down'
    assert env.svc.resolve('alice', 'github').access_token == old          # not yet expired: still used
    assert env.vault.get('alice', 'github').status == 'active'


def test_expired_without_refresh_token_needs_reconnect(env):
    env.fake.issue_refresh = False
    env.fake.expires_in = 3600
    link(env)
    with env.engine.begin() as c:
        c.execute(text("UPDATE connected_accounts SET expires_at=:t"), {'t': utcnow() - timedelta(seconds=5)})
    with pytest.raises(ConnectedAccountRequired) as ei:
        env.svc.resolve('alice', 'github')
    assert ei.value.reason == 'reauth_required'


def test_missing_link_scope_and_non_user_callers(env):
    with pytest.raises(ConnectedAccountRequired) as ei:
        env.svc.resolve('alice', 'github')
    assert ei.value.reason == 'not_connected' and ei.value.connect_url == \
        'https://sajha.test/account/connections?connect=github'
    link(env, scopes=None)
    with pytest.raises(ConnectedAccountRequired) as ei:
        env.svc.resolve('alice', 'github', ['admin:org'])
    assert ei.value.reason == 'insufficient_scope' and ei.value.scopes == ['admin:org']
    assert 'scope=admin%3Aorg' in ei.value.connect_url
    assert env.svc.resolve('alice', 'github', ['public_repo'])      # implied by repo
    for who in ('anonymous', 'apikey:ci', ''):
        with pytest.raises(ConnectedAccountRequired) as ei:
            env.svc.resolve(who, 'github')
        assert ei.value.reason == 'sign_in_required'


def test_incremental_consent_keeps_granted_scopes(env):
    link(env)
    url = env.svc.start('alice', 'github', browser_nonce='n', scopes=['admin:org'])
    scope = parse_qs(urlsplit(url).query)['scope'][0].split()
    assert set(scope) == {'read:user', 'repo', 'admin:org'}


def test_per_user_isolation_in_tools(env):
    link(env, 'alice')
    link(env, 'bob')
    tool = load_tool('github_list_my_repos')
    with as_user('alice'):
        a = tool.execute_with_tracking({})
    with as_user('bob'):
        b = tool.execute_with_tracking({})
    assert a['account'] == 'octo-alice' and a['repositories'][0]['full_name'] == 'octo-alice/hello'
    assert b['account'] == 'octo-bob' and b['repositories'][0]['full_name'] == 'octo-bob/hello'
    users = [u for (_m, url, u) in env.fake.api_calls if url.endswith('/user/repos?per_page=30&sort=updated'
                                                                        '&visibility=all&affiliation=owner%2C'
                                                                        'collaborator%2Corganization_member')]
    assert users == ['octo-alice', 'octo-bob']
    with as_user('carol'), pytest.raises(ConnectedAccountRequired):
        tool.execute_with_tracking({})


def test_per_user_tools_are_never_cached(env):
    from sajha.core.cache import get_tool_ttl
    assert get_tool_ttl('github_list_my_repos', {'cache_ttl': 600, 'auth': {'connected_account': 'github'}}) == 0
    assert get_tool_ttl('x', {'cache_ttl': 600}) == 600


def test_api_401_refreshes_once_then_asks_to_reconnect(env):
    link(env)
    tool = load_tool('github_list_my_repos')
    env.fake.reject_next_api = 1
    with as_user('alice'):
        assert tool.execute_with_tracking({})['count'] == 1             # refreshed and retried
    assert env.events[-1][0] in ('connected_account_refreshed',)
    env.fake.reject_next_api = 2
    with as_user('alice'), pytest.raises(ConnectedAccountRequired) as ei:
        tool.execute_with_tracking({})
    assert ei.value.reason == 'reauth_required'
    assert env.vault.get('alice', 'github').status == 'reauth_required'


def test_arguments_are_validated_before_asking_for_a_connection(env):
    from sajha.tools.base_mcp_tool import ToolArgumentError
    tool = load_tool('github_create_issue')
    with as_user('alice'), pytest.raises(ToolArgumentError):
        tool.execute_with_tracking({'owner': 'o'})


def test_tool_is_listed_only_when_its_provider_is_configured(env):
    tool = load_tool('github_list_my_repos')
    assert tool.enabled
    set_registry(ProviderRegistry.load(raw={}, use_env=False))
    assert not tool.enabled
    set_registry(env.registry)


# ── the example tools against the (fake) real APIs ──────────────────

def test_github_create_issue(env):
    link(env)
    with as_user('alice'):
        out = load_tool('github_create_issue').execute_with_tracking(
            {'owner': 'octo', 'repo': 'hello', 'title': 'Bug', 'body': 'Steps', 'labels': ['bug']})
    assert out == {'number': 7, 'url': 'https://github.com/x/y/issues/7', 'title': 'Bug', 'state': 'open',
                   'created_by': 'octo-alice'}
    assert load_tool('github_create_issue').config['annotations']['destructiveHint'] is True


def test_slack_post_message_and_invalid_auth(env):
    link(env, pid='slack')
    tool = load_tool('slack_post_message')
    with as_user('alice'):
        out = tool.execute_with_tracking({'channel': '#general', 'text': 'hi'})
    assert out['ok'] and out['channel'] == '#general' and out['ts'] == '1.2'
    with env.engine.begin() as c:     # a token Slack no longer knows: refresh once, then it works
        doc = env.vault.tokens(env.vault.get('alice', 'slack'))
    env.fake.access.pop(doc['access_token'])
    with as_user('alice'):
        assert tool.execute_with_tracking({'channel': '#general', 'text': 'again'})['ok']


def test_google_drive_search_escapes_the_query(env):
    from sajha.accounts.tools.google import drive_query
    assert drive_query("it's") == "fullText contains 'it\\'s' and trashed = false"
    link(env, pid='google')
    with as_user('alice'):
        out = load_tool('google_drive_search').execute_with_tracking({'query': 'budget', 'limit': 5})
    assert out['files'][0]['name'] == 'Budget' and out['count'] == 1
    sent = [u for (_m, u, _who) in env.fake.api_calls if 'drive/v3/files' in u][-1]
    assert 'pageSize=5' in sent and 'trashed' in sent


def test_ms365_list_my_events(env):
    link(env, pid='microsoft')
    with as_user('alice'):
        out = load_tool('ms365_list_my_events').execute_with_tracking({'days': 3})
    assert out['events'][0]['subject'] == 'Standup'
    sent = [u for (_m, u, _who) in env.fake.api_calls if 'calendarView' in u][-1]
    assert 'startDateTime=' in sent and 'endDateTime=' in sent


def test_connected_http_request_guards(env):
    link(env)
    tool = load_tool('connected_http_request')
    with as_user('alice'):
        assert tool.execute_with_tracking({'path': '/user'})['body']['login'] == 'octo-alice'
        for bad in ('/user/../admin', '//evil.test/x', '/admin/secret', 'https://evil.test/'):
            with pytest.raises(Exception, match='path|pattern'):
                tool.execute_with_tracking({'path': bad})
        with pytest.raises(Exception):
            tool.execute_with_tracking({'path': '/user', 'method': 'DELETE'})


def test_token_never_leaves_the_providers_hosts(env):
    p = env.registry.get('github')
    ahttp.check_api_url(p, 'https://api.github.com/user')
    for bad in ('https://evil.test/user', 'http://api.github.com/user', 'https://u:p@api.github.com/',
                'https://api.github.com.evil.test/'):
        with pytest.raises(ahttp.TokenHostError):
            ahttp.check_api_url(p, bad)


def test_disconnect_revokes_and_deletes(env):
    link(env)
    rt = env.vault.tokens(env.vault.get('alice', 'github'))['refresh_token']
    assert env.svc.disconnect('alice', 'github', actor='alice')
    assert env.fake.revoked == [rt] and env.vault.get('alice', 'github') is None
    assert env.events[-1][0] == 'connected_account_disconnected'
    assert env.svc.disconnect('alice', 'github') is False
    link(env)
    assert env.svc.disconnect('alice', 'github', actor='admin')          # an administrator unlinking
    assert env.events[-1][3]['by_admin'] is True


def test_no_token_in_logs(env, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    env.fake.expires_in = 60
    link(env)
    env.svc.resolve('alice', 'github')
    with as_user('alice'):
        load_tool('github_list_my_repos').execute_with_tracking({})
    for tok in list(env.fake.access) + list(env.fake.refresh) + [SECRET]:
        assert tok not in caplog.text


# ── multi-worker: flows and refresh through a shared state store ────

def test_flow_started_on_one_worker_completes_on_another(env, tmp_path):
    from sajha.core.state.database import DatabaseStateStore
    url = f'sqlite:///{tmp_path / "state.db"}'
    w1 = ConnectedAccountsService(env.registry, env.vault, DatabaseStateStore(prefix='t:', url=url))
    w2 = ConnectedAccountsService(env.registry, env.vault, DatabaseStateStore(prefix='t:', url=url))
    auth_url = w1.start('alice', 'github', browser_nonce='n')
    back = env.fake.approve(auth_url)
    assert w2.complete('alice', 'github', state=back['state'], code=back['code'], browser_nonce='n')
    with pytest.raises(OAuthFlowError):         # and only once, wherever it is retried
        w1.complete('alice', 'github', state=back['state'], code=back['code'], browser_nonce='n')
    # separate per-process memory stores (state.backend: memory with two workers) cannot do this
    w3 = ConnectedAccountsService(env.registry, env.vault, MemoryStateStore('a:'))
    w4 = ConnectedAccountsService(env.registry, env.vault, MemoryStateStore('b:'))
    back = env.fake.approve(w3.start('alice', 'github', browser_nonce='n'))
    with pytest.raises(OAuthFlowError):
        w4.complete('alice', 'github', state=back['state'], code=back['code'], browser_nonce='n')


def test_concurrent_refresh_on_two_workers_refreshes_once(env, tmp_path):
    from sajha.core.state.database import DatabaseStateStore
    env.fake.expires_in = 60
    link(env)
    env.fake.expires_in = 3600
    url = f'sqlite:///{tmp_path / "state2.db"}'
    workers = [ConnectedAccountsService(env.registry, env.vault, DatabaseStateStore(prefix='t:', url=url))
               for _ in range(2)]
    for w in workers:               # each worker's store is up before the race (as after start-up)
        w.store.get('warm-up')
    before = len([r for r in env.fake.token_requests if r['grant_type'] == 'refresh_token'])
    out, errors = [], []

    def go(w):
        try:
            out.append(w.resolve('alice', 'github').access_token)
        except Exception as e:     # pragma: no cover - reported below
            errors.append(e)
    threads = [threading.Thread(target=go, args=(w,)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert not errors, errors
    refreshes = len([r for r in env.fake.token_requests if r['grant_type'] == 'refresh_token']) - before
    assert refreshes == 1 and len(set(out)) == 1 and out[0] in env.fake.access


# ── MCP (both eras), REST and Ask ───────────────────────────────────

class _Exc:
    pass


def test_mcp_responder_modern_and_legacy(env):
    from sajha.accounts.respond import URL_ELICITATION_REQUIRED, mcp_response
    from sajha.core.mcp_2025_11_25 import MCPError
    from sajha.core.mcp_tool_context import ModernToolContext
    exc = env.svc.required('github', 'not_connected', 'alice')
    # modern, client can open URLs: an MRTR URL elicitation
    ctx = ModernToolContext(client_capabilities={'elicitation': {'url': {}}})
    tok = ctx.activate()
    try:
        with pytest.raises(InputRequired) as ei:
            mcp_response(exc, 'modern', None)
        req = ei.value.requests['sajha.connect.github']
        assert req['method'] == 'elicitation/create' and req['params']['mode'] == 'url'
        assert req['params']['url'] == 'https://sajha.test/account/connections?connect=github'
        assert not isinstance(ei.value, ConnectedAccountRequired)
    finally:
        ctx.deactivate(tok)
    # modern retry after "accept" but still not linked: a tool error, not another round
    ctx = ModernToolContext(client_capabilities={'elicitation': {'url': {}}},
                            input_responses={'sajha.connect.github': {'action': 'accept'}})
    tok = ctx.activate()
    try:
        r = mcp_response(exc, 'modern', None)
        assert r['isError'] and 'still not linked' in r['content'][0]['text']
    finally:
        ctx.deactivate(tok)
    # modern, form-only client: a tool error naming the URL
    ctx = ModernToolContext(client_capabilities={'elicitation': {}})
    tok = ctx.activate()
    try:
        r = mcp_response(exc, 'modern', None)
        assert r['isError'] and 'account/connections?connect=github' in r['content'][0]['text']
        assert r['_meta']['sajha/connected_account']['provider'] == 'github'
    finally:
        ctx.deactivate(tok)
    # legacy with URL elicitation: -32042
    with pytest.raises(MCPError) as ei:
        mcp_response(exc, 'legacy', {'client_capabilities': {'elicitation': {'form': {}, 'url': {}}}})
    assert ei.value.code == URL_ELICITATION_REQUIRED == -32042
    assert ei.value.data['elicitations'][0]['url'].endswith('connect=github')
    # legacy without: tool error; and an API-key caller is never sent to a URL
    assert mcp_response(exc, 'legacy', {'client_capabilities': {}})['isError']
    nobody = env.svc.required('github', 'sign_in_required', 'apikey:x')
    assert mcp_response(nobody, 'legacy', {'client_capabilities': {'elicitation': {'url': {}}}})['isError']


@pytest.fixture(scope='module')
def app_client():
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        yield c


def _bearer():
    from sajha.auth.jwt_handler import create_access_token
    return {'Authorization': 'Bearer ' + create_access_token('admin', ['admin'])}


def _modern_call(c, name, args, caps=None, extra=None):
    params = {'name': name, 'arguments': args, '_meta': {
        'io.modelcontextprotocol/protocolVersion': '2026-07-28',
        'io.modelcontextprotocol/clientCapabilities': caps or {},
        'io.modelcontextprotocol/clientInfo': {'name': 'pytest', 'version': '1'}}, **(extra or {})}
    return c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': params},
                  headers={**_bearer(), 'MCP-Protocol-Version': '2026-07-28', 'Mcp-Method': 'tools/call',
                           'Mcp-Name': name, 'Accept': 'application/json, text/event-stream'})


def test_mcp_modern_end_to_end(env, app_client):
    c = app_client
    r = _modern_call(c, 'github_list_my_repos', {}, caps={'elicitation': {'url': {}}}).json()['result']
    assert r['resultType'] == 'input_required', r
    req = r['inputRequests']['sajha.connect.github']
    assert req['params']['mode'] == 'url' and 'connect=github' in req['params']['url']
    link(env, 'admin')                                  # the user follows the URL and links GitHub
    r2 = _modern_call(c, 'github_list_my_repos', {}, caps={'elicitation': {'url': {}}},
                      extra={'inputResponses': {'sajha.connect.github': {'action': 'accept'}},
                             'requestState': r['requestState']}).json()['result']
    assert r2['resultType'] == 'complete' and not r2.get('isError'), r2
    assert r2['structuredContent']['account'] == 'octo-admin'
    env.svc.disconnect('admin', 'github')
    r3 = _modern_call(c, 'github_list_my_repos', {}).json()['result']   # no URL elicitation: tool error
    assert r3['isError'] and 'connect=github' in r3['content'][0]['text']


def test_mcp_legacy_end_to_end(env, app_client):
    c = app_client
    h = {**_bearer(), 'Accept': 'application/json, text/event-stream'}
    init = c.post('/mcp', headers=h, json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-11-25', 'capabilities': {'elicitation': {'form': {}, 'url': {}}},
        'clientInfo': {'name': 't', 'version': '1'}}})
    sid = init.headers['Mcp-Session-Id']
    h2 = {**h, 'Mcp-Session-Id': sid, 'MCP-Protocol-Version': '2025-11-25'}
    c.post('/mcp', headers=h2, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    body = c.post('/mcp', headers=h2, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                            'params': {'name': 'github_list_my_repos', 'arguments': {}}}).json()
    assert body['error']['code'] == -32042
    assert body['error']['data']['elicitations'][0]['mode'] == 'url'
    link(env, 'admin')
    body = c.post('/mcp', headers=h2, json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                                            'params': {'name': 'github_list_my_repos', 'arguments': {}}}).json()
    assert not body['result'].get('isError') and 'octo-admin' in body['result']['content'][0]['text']
    env.svc.disconnect('admin', 'github')


def test_rest_answers_428_with_the_connect_url(env, app_client):
    r = app_client.post('/api/tools/execute', headers=_bearer(),
                        json={'tool': 'github_list_my_repos', 'arguments': {}})
    assert r.status_code == 428
    body = r.json()
    assert body['error_code'] == 'connected_account_required' and body['provider'] == 'github'
    assert body['connect_url'] == 'https://sajha.test/account/connections?connect=github'


def test_ask_shows_a_connect_prompt(env):
    from sajha.ai.intelligence import IntelligenceService
    from sajha.ai.llm import RequestContext
    from sajha.ai.llm.settings import AskSettings
    from tests.ai.conftest import ToolBox, make_gateway
    tb = ToolBox(with_calc=False)
    tb.add(load_tool('github_list_my_repos'))
    gw = make_gateway({'aliases': {'default': ['mock/mock-scripted']}})
    gw.providers['mock'].set_script([{'tool_calls': [{'name': 'github_list_my_repos', 'arguments': {},
                                                      'id': 'g1'}]}, {'text': 'done'}])
    svc = IntelligenceService(gw, tb, settings=AskSettings(audit=False), audit=lambda e: None)
    with as_user('alice'):
        events = list(svc.stream_ask('List my GitHub repositories', RequestContext(user_id='alice')))
    kinds = [e['type'] for e in events]
    assert 'needs_connection' in kinds
    ev = next(e for e in events if e['type'] == 'needs_connection')
    assert ev['provider'] == 'github' and ev['provider_title'] == 'GitHub'
    assert ev['connect_url'] == '/account/connections?connect=github'
    done = events[-1]['result']
    assert done['stopped_by'] == 'needs_connection' and 'Connect' in done['answer']
    assert done['connections'][0]['provider'] == 'github'


def test_ask_page_script_renders_the_connect_card():
    js = open('sajha/web/static/js/ask.js', encoding='utf-8').read()
    assert "case 'needs_connection':" in js and "'Connect ' + p.provider_title" in js


# ── the pages ───────────────────────────────────────────────────────

def test_connect_page_flow_and_csrf(env, app_client):
    c = app_client
    c.cookies.clear()
    r = c.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
    cookies = dict(r.cookies)
    page = c.get('/account/connections?connect=github', cookies=cookies)
    assert page.status_code == 200 and 'Connect GitHub' in page.text and 'acct-wanted' in page.text
    import re
    csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', page.text).group(1)
    bad = c.post('/account/connections/github/connect', data={'csrf': 'nope'}, cookies=cookies,
                 follow_redirects=False)
    assert bad.status_code == 403
    go = c.post('/account/connections/github/connect', data={'csrf': csrf}, cookies=cookies, follow_redirects=False)
    assert go.status_code == 303 and go.headers['location'].startswith(f'{AUTH}/authorize?')
    flow = go.cookies.get('sajha_acct_flow')
    assert flow and 'httponly' in go.headers['set-cookie'].lower()
    back = env.fake.approve(go.headers['location'], login='octo-admin')
    cb = c.get(f"/account/connections/github/callback?state={back['state']}&code={back['code']}",
               cookies={**cookies, 'sajha_acct_flow': flow}, follow_redirects=False)
    assert cb.status_code == 303 and cb.headers['location'] == '/account/connections?linked=github'
    page = c.get('/account/connections?linked=github', cookies=cookies)
    assert 'is linked' in page.text and 'octo-admin' in page.text
    tok = env.vault.tokens(env.vault.get('admin', 'github'))['access_token']
    assert tok not in page.text
    admin = c.get('/admin/connections', cookies=cookies)
    assert admin.status_code == 200 and 'octo-admin' in admin.text and tok not in admin.text
    api = c.get('/api/accounts/connections', cookies=cookies).json()
    assert api['connections'][0]['account_login'] == 'octo-admin' and tok not in json.dumps(api)
    assert c.delete('/api/accounts/connections/github', cookies=cookies).status_code == 403   # no CSRF header
    out = c.post('/account/connections/github/disconnect', data={'csrf': csrf}, cookies=cookies,
                 follow_redirects=False)
    assert out.status_code == 303 and env.vault.get('admin', 'github') is None
    # a callback replayed in another browser (no flow cookie) is refused
    go = c.post('/account/connections/github/connect', data={'csrf': csrf}, cookies=cookies, follow_redirects=False)
    back = env.fake.approve(go.headers['location'], login='octo-admin')
    c.cookies.clear()                                   # the client's jar holds the flow cookie: drop it
    cb = c.get(f"/account/connections/github/callback?state={back['state']}&code={back['code']}",
               cookies=cookies, follow_redirects=False)
    assert cb.status_code == 400 and 'different browser' in cb.text
    c.cookies.clear()


def test_audit_events_reach_the_audit_log(tmp_path, monkeypatch):
    """Without the test double: the service writes audit_log rows through AuditLogger."""
    from sajha.core import audit as audit_mod
    rows = []

    class Rec:
        def log(self, action, **kw):
            rows.append((action, kw))
    monkeypatch.setattr(audit_mod, '_audit', Rec())
    ConnectedAccountsService.audit('connected_account_linked', 'alice', 'github', '1.2.3.4', account='octo')
    assert rows == [('connected_account_linked', {'user_id': 'alice', 'resource_type': 'connected_account',
                                                  'resource_id': 'github', 'details': '{"account": "octo"}',
                                                  'ip_address': '1.2.3.4'})]


def test_vault_table_is_in_both_schema_files():
    from pathlib import Path
    for dialect in ('sqlite', 'postgresql'):
        sql = '\n'.join(f.read_text(encoding='utf-8') for f in sorted(Path('db/scripts', dialect).glob('*.sql')))
        assert 'CREATE TABLE IF NOT EXISTS connected_accounts' in sql and 'token_ciphertext' in sql, dialect


def test_postgresql_without_the_table_is_reported_not_created(monkeypatch):
    from sajha.accounts.vault import VaultSchemaMissing

    class _Insp:
        def has_table(self, name):
            return False

    class _Eng:
        class dialect:
            name = 'postgresql'
    monkeypatch.setattr('sqlalchemy.inspect', lambda _e: _Insp())
    with pytest.raises(VaultSchemaMissing, match='schema file'):
        TokenVault(engine=_Eng(), key_provider=LocalKeyProvider(KEY1)).ensure_table()


# ── federation: per-user token passthrough ──────────────────────────

class _AuthRecordingUpstream:
    """An MCP SDK server on a local port that records each request's Authorization header."""

    def __init__(self):
        import socket
        import uvicorn
        from sajha.examples.federation.units_server import build_server
        self.seen = []
        app = build_server('passthrough-upstream').streamable_http_app()
        seen = self.seen

        async def recording(scope, receive, send):
            if scope['type'] == 'http':
                hdrs = dict(scope.get('headers') or [])
                seen.append(hdrs.get(b'authorization', b'').decode())
            await app(scope, receive, send)
        s = socket.socket()
        s.bind(('127.0.0.1', 0))
        self.port = s.getsockname()[1]
        s.close()
        self.url = f'http://127.0.0.1:{self.port}/mcp'
        self._uv = uvicorn.Server(uvicorn.Config(recording, host='127.0.0.1', port=self.port, log_level='warning',
                                                 lifespan='on'))
        self._t = threading.Thread(target=self._uv.run, daemon=True)
        self._t.start()
        deadline = time.time() + 10
        while not self._uv.started and time.time() < deadline:
            time.sleep(0.02)
        assert self._uv.started

    def stop(self):
        self._uv.should_exit = True
        self._t.join(10)


class _Reg:
    def __init__(self):
        self.tools = {}

    def register_tool(self, t):
        self.tools[t.name] = t

    def unregister_tool(self, n):
        self.tools.pop(n, None)

    def get_tool(self, n):
        return self.tools.get(n)


def test_federation_upstream_config_rules():
    from sajha.federation.config import ConfigError, UpstreamConfig
    ok = UpstreamConfig.from_dict({'id': 'gh', 'url': 'https://mcp.example.com/mcp',
                                   'auth': {'type': 'connected_account', 'provider': 'github', 'scopes': 'repo',
                                            'discovery': {'type': 'bearer', 'token_ref': 'env:X'}}})
    assert ok.auth['scopes'] == ['repo']
    for bad, msg in [({'auth': {'type': 'connected_account'}}, 'provider'),
                     ({'auth': {'type': 'connected_account', 'provider': 'github'}, 'cache_ttl': 60}, 'per user'),
                     ({'auth': {'type': 'connected_account', 'provider': 'github',
                                'discovery': {'type': 'bearer', 'token': 'inline'}}}, 'reference'),
                     ({'auth': {'type': 'connected_account', 'provider': 'github'}, 'transport': 'stdio',
                       'command': '/bin/true'}, 'HTTP transport')]:
        with pytest.raises(ConfigError, match=msg):
            UpstreamConfig.from_dict({'id': 'gh', 'url': 'https://mcp.example.com/mcp', **bad})


def test_federation_passes_each_users_own_token(env, tmp_path):
    pytest.importorskip('mcp.server.mcpserver')
    from sajha.federation.config import FederationSettings
    from sajha.federation.manager import FederationManager
    from sajha.federation.store import FederationStore
    up = _AuthRecordingUpstream()
    settings = FederationSettings(enabled=True, allow_localhost=True, require_approval=False, startup_wait_seconds=10,
                                  default_timeout_seconds=10, upstreams=[{
                                      'id': 'units', 'url': up.url,
                                      'auth': {'type': 'connected_account', 'provider': 'github'}}])
    reg = _Reg()
    m = FederationManager(reg, settings, FederationStore(str(tmp_path / 'fed.json')))
    m.start()
    try:
        assert m.wait_until_discovered(10)
        tool = reg.tools['units__celsius_to_fahrenheit']
        assert up.seen and all(h == '' for h in up.seen)          # discovery carried no user token
        link(env, 'alice')
        link(env, 'bob')
        tokens = {u: env.vault.tokens(env.vault.get(u, 'github'))['access_token'] for u in ('alice', 'bob')}
        for user in ('alice', 'bob'):
            up.seen.clear()
            with as_user(user):
                out = tool.execute_with_tracking({'celsius': 100})
            assert '212' in json.dumps(out)
            assert up.seen and set(up.seen) == {f'Bearer {tokens[user]}'}, (user, up.seen)
        with as_user('carol'), pytest.raises(ConnectedAccountRequired) as ei:
            tool.execute_with_tracking({'celsius': 1})
        assert ei.value.reason == 'not_connected'
        assert 'connected_account' not in json.dumps(m.status('units')['definition'].get('auth', {}).get('discovery', {}))
    finally:
        m.stop()
        up.stop()
