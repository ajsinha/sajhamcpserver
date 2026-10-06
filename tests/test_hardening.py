"""
Security hardening: secrets, tool access (REST, MCP both eras, A2A, async), sign-in
protection, password change, API key lists, sensitive endpoints, config fixes, nginx.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import json
import logging
import os
import stat
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

PV = 'io.modelcontextprotocol/protocolVersion'
META = {PV: '2026-07-28', 'io.modelcontextprotocol/clientCapabilities': {},
        'io.modelcontextprotocol/clientInfo': {'name': 'pytest', 'version': '1'}}
ALLOWED_TOOL = 'calc_compound_interest'
OTHER_TOOL = 'calc_capm'
GOOD_PASSWORD = 'Hardening-Pass-1'


# ── fixtures ─────────────────────────────────────────────────────

@pytest.fixture(scope='module')
def client():
    os.environ.pop('SAJHA_MCP_CONFORMANCE_FIXTURES', None)
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_throttle():
    from sajha.security import _login_throttle
    _login_throttle.reset()
    yield
    _login_throttle.reset()


@pytest.fixture(scope='module')
def admin_headers(client):
    from sajha.security import _login_throttle
    _login_throttle.reset()
    r = client.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'})
    assert r.status_code == 200, r.text
    return {'Authorization': f"Bearer {r.json()['token']}"}


def _make_user(role: str, password: str = GOOD_PASSWORD, must_change: bool = False) -> str:
    from sajha.db.engine import get_db_session
    from sajha.db.dao import UserDAO, RoleDAO
    from sajha.db.models import User
    from sajha.auth.password import hash_password
    uid = f'hard_{role}_{uuid.uuid4().hex[:8]}'
    db = get_db_session()
    try:
        user = User(user_id=uid, user_name=uid, email='', password_hash=hash_password(password), enabled=True)
        user.must_change_password = must_change
        user.roles.append(RoleDAO(db).get_or_create(role))
        UserDAO(db).create(user)
    finally:
        db.close()
    return uid


def _drop_user(uid: str):
    from sajha.db.engine import get_db_session
    from sajha.db.dao import UserDAO
    db = get_db_session()
    try:
        user = UserDAO(db).get_by_user_id(uid)
        if user:
            UserDAO(db).delete(user)
    finally:
        db.close()


def _login(client, uid, password=GOOD_PASSWORD):
    r = client.post('/api/auth/login', json={'user_id': uid, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': f"Bearer {r.json()['token']}"}


@pytest.fixture(scope='module')
def user_headers(client):
    uid = _make_user('user')
    yield _login(client, uid)
    _drop_user(uid)


@pytest.fixture(scope='module')
def viewer_headers(client):
    uid = _make_user('viewer')
    yield _login(client, uid)
    _drop_user(uid)


def _api_key(mode: str, tools) -> str:
    from sajha.db.engine import get_db_session
    from sajha.db.dao import ApiKeyDAO
    from sajha.db.models import ApiKey
    raw = f'sja_{uuid.uuid4().hex}{uuid.uuid4().hex}'
    db = get_db_session()
    try:
        dao = ApiKeyDAO(db)
        dao.create(ApiKey(key_hash=dao.hash_key(raw), key_prefix=raw[:8], name=f'hard-{mode}-{raw[-6:]}',
                          tool_access_mode=mode, tool_access_list=json.dumps(tools)))
    finally:
        db.close()
    return raw


def legacy(client, method, params=None, headers=None):
    return client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}},
                       headers=headers or {})


def modern(client, method, params=None, headers=None):
    params = dict(params or {})
    params['_meta'] = dict(META)
    hdrs = {'MCP-Protocol-Version': '2026-07-28', 'Mcp-Method': method,
            'Accept': 'application/json, text/event-stream'}
    if method == 'tools/call':
        hdrs['Mcp-Name'] = params['name']
    hdrs.update(headers or {})
    return client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params},
                       headers=hdrs)


def _names(resp):
    body = resp.json()
    assert 'result' in body, body
    return {t['name'] for t in body['result']['tools']}


CI_ARGS = {'principal': 1000, 'rate': 5, 'years': 2}


# ── 1. secrets ───────────────────────────────────────────────────

class TestSecrets:
    def test_shipped_placeholder_is_refused(self):
        from sajha.core.server_secrets import check_not_shipped, InsecureSecretError
        for value in ('sajha-jwt-secret-change-in-production', 'sajha-session-secret-change-in-production',
                      'sajha-jwt-secret-change-me', 'dev-secret-change-in-production'):
            with pytest.raises(InsecureSecretError):
                check_not_shipped('auth.jwt.secret', value, 'JWT_SECRET')
        check_not_shipped('auth.jwt.secret', 'x' * 48, 'JWT_SECRET')

    def test_get_settings_refuses_shipped_env_value(self, monkeypatch):
        from sajha.core.config import get_settings
        from sajha.core.server_secrets import InsecureSecretError
        monkeypatch.setenv('SAJHA_JWT_SECRET', 'sajha-jwt-secret-change-in-production')
        get_settings.cache_clear()
        try:
            with pytest.raises(InsecureSecretError):
                get_settings()
        finally:
            monkeypatch.delenv('SAJHA_JWT_SECRET')
            get_settings.cache_clear()
        assert len(get_settings().jwt_secret) >= 32

    def test_empty_secrets_are_generated_persisted_and_stable(self, tmp_path, monkeypatch):
        from sajha.core.server_secrets import resolve_settings_secrets
        path = tmp_path / 'secrets' / 's.json'
        monkeypatch.setenv('SAJHA_AUTH_SECRETS_FILE', str(path))
        first = SimpleNamespace(jwt_secret='', secret_key='')
        resolve_settings_secrets(first)
        assert len(first.jwt_secret) >= 48 and len(first.secret_key) >= 48
        assert first.jwt_secret != first.secret_key
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        second = SimpleNamespace(jwt_secret='', secret_key='')
        resolve_settings_secrets(second)              # another process / restart
        assert (second.jwt_secret, second.secret_key) == (first.jwt_secret, first.secret_key)
        configured = SimpleNamespace(jwt_secret='y' * 40, secret_key='')
        resolve_settings_secrets(configured)          # configured values win
        assert configured.jwt_secret == 'y' * 40

    def test_yaml_ships_no_secret(self):
        text = Path('config/application.yml').read_text()
        assert 'change-in-production' not in text
        assert '${JWT_SECRET:}' in text and '${SESSION_SECRET:}' in text

    def test_secrets_dir_is_git_ignored(self):
        assert 'data/secrets/' in Path('.gitignore').read_text()

    def test_mrtr_secret_derives_from_the_persisted_session_secret(self, monkeypatch):
        import hashlib
        import hmac
        from sajha.core import mcp_mrtr
        from sajha.core.config import get_settings
        monkeypatch.delenv('SAJHA_MCP_MRTR_STATE_SECRET', raising=False)
        mcp_mrtr.reset_secret_cache()
        try:
            expected = hmac.new(get_settings().secret_key.encode(), b'sajha/mcp/mrtr-request-state/v1',
                                hashlib.sha256).digest()
            assert mcp_mrtr._secret() == expected
        finally:
            mcp_mrtr.reset_secret_cache()


# ── 2. MCP tool access ───────────────────────────────────────────

class TestMcpToolAccess:
    def test_anonymous_sees_and_runs_no_registry_tool_by_default(self, client):
        assert _names(legacy(client, 'tools/list')) == set()
        assert _names(modern(client, 'tools/list')) == set()
        r = legacy(client, 'tools/call', {'name': ALLOWED_TOOL, 'arguments': CI_ARGS}).json()
        assert r['error']['code'] == -32002
        r = modern(client, 'tools/call', {'name': ALLOWED_TOOL, 'arguments': CI_ARGS}).json()
        assert r['error']['code'] == -32010

    def test_unknown_tool_is_still_invalid_params_for_anonymous(self, client):
        r = legacy(client, 'tools/call', {'name': 'no_such_tool', 'arguments': {}}).json()
        assert r['error']['code'] == -32602

    def test_anonymous_allowlist(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_ANONYMOUS_TOOLS', 'calc_compound_*')
        assert _names(legacy(client, 'tools/list')) == {ALLOWED_TOOL}
        assert _names(modern(client, 'tools/list')) == {ALLOWED_TOOL}
        r = legacy(client, 'tools/call', {'name': ALLOWED_TOOL, 'arguments': CI_ARGS}).json()
        assert 'result' in r, r
        r = legacy(client, 'tools/call', {'name': OTHER_TOOL, 'arguments': {}}).json()
        assert r['error']['code'] == -32002

    def test_anonymous_disabled_requires_credentials(self, client, monkeypatch, admin_headers):
        monkeypatch.setenv('SAJHA_MCP_ANONYMOUS_ENABLED', 'false')
        assert legacy(client, 'tools/list').status_code == 401
        assert modern(client, 'tools/list').status_code == 401
        assert legacy(client, 'tools/list', headers=admin_headers).status_code == 200
        r = client.post('/a2a', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tasks/get', 'params': {'id': 'x'}})
        assert r.status_code == 401

    def test_admin_sees_everything_and_cache_scope_is_private(self, client, admin_headers):
        names = _names(legacy(client, 'tools/list', headers=admin_headers))
        assert ALLOWED_TOOL in names and OTHER_TOOL in names
        res = modern(client, 'tools/list', headers=admin_headers).json()['result']
        assert res['cacheScope'] == 'private'
        assert modern(client, 'tools/list').json()['result']['cacheScope'] == 'public'

    def test_viewer_sees_tools_but_cannot_run_them(self, client, viewer_headers):
        assert ALLOWED_TOOL in _names(legacy(client, 'tools/list', headers=viewer_headers))
        r = legacy(client, 'tools/call', {'name': ALLOWED_TOOL, 'arguments': CI_ARGS}, headers=viewer_headers)
        assert r.json()['error']['code'] == -32002
        r = client.post('/api/tools/execute', json={'tool': ALLOWED_TOOL, 'arguments': CI_ARGS},
                        headers=viewer_headers)
        assert r.status_code == 403

    def test_user_role_runs_tools(self, client, user_headers):
        r = legacy(client, 'tools/call', {'name': ALLOWED_TOOL, 'arguments': CI_ARGS}, headers=user_headers)
        assert 'result' in r.json(), r.text

    def test_websocket_applies_the_policy(self, client):
        with client.websocket_connect('/mcp/ws') as ws:
            ws.send_text(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}))
            assert json.loads(ws.receive_text())['result']['tools'] == []
            ws.send_text(json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                                     'params': {'name': ALLOWED_TOOL, 'arguments': CI_ARGS}}))
            assert json.loads(ws.receive_text())['error']['code'] == -32002

    def test_websocket_bad_token_is_refused(self, client):
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/mcp/ws?token=not-a-jwt') as ws:
                ws.receive_text()

    def test_mcp_logging_set_level_does_not_touch_server_log_for_anonymous(self, client):
        root = logging.getLogger()
        before = root.level
        r = legacy(client, 'logging/setLevel', {'level': 'critical'}).json()
        assert r['result'] == {}
        assert root.level == before


# ── 3. A2A ───────────────────────────────────────────────────────

class TestA2A:
    def _send(self, client, text, headers=None):
        return client.post('/a2a', headers=headers or {}, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'tasks/send',
            'params': {'message': {'parts': [{'type': 'text', 'text': text}]}}}).json()

    def test_anonymous_cannot_run_a_tool(self, client):
        res = self._send(client, f'please run {ALLOWED_TOOL}')['result']
        assert res['status']['state'] == 'failed'
        assert 'Access denied' in json.dumps(res)

    def test_user_runs_tool_and_others_cannot_read_the_task(self, client, user_headers, viewer_headers):
        res = self._send(client, f'please run {ALLOWED_TOOL}', user_headers)['result']
        assert res['status']['state'] in ('completed', 'failed')
        assert 'Access denied' not in json.dumps(res)
        get = {'jsonrpc': '2.0', 'id': 2, 'method': 'tasks/get', 'params': {'id': res['id']}}
        assert 'result' in client.post('/a2a', json=get, headers=user_headers).json()
        assert 'error' in client.post('/a2a', json=get, headers=viewer_headers).json()
        assert 'error' in client.post('/a2a', json=get).json()


# ── 4. async execution ───────────────────────────────────────────

class TestAsyncDelivery:
    def _router(self, tmp_path, allowed=(), private=False):
        from sajha.core.async_executor import DeliveryRouter
        return DeliveryRouter(file_base_dir=str(tmp_path), webhook_allowed_urls=lambda: list(allowed),
                              webhook_allow_private=private)

    @pytest.mark.parametrize('dest', ['../escape.json', '/etc/passwd', 'a/../../b.json', '', 'C:\\x.json'])
    def test_file_destination_must_stay_inside_base_dir(self, tmp_path, dest):
        from sajha.core.async_executor import DeliveryError
        with pytest.raises(DeliveryError):
            self._router(tmp_path).validate('file', dest)

    def test_file_destination_inside_base_dir(self, tmp_path):
        assert self._router(tmp_path).resolve_file_destination('out/r.json') == (tmp_path / 'out/r.json').resolve()

    def test_file_delivery_writes_inside_base_dir(self, tmp_path):
        from sajha.core.async_executor import AsyncTask, AsyncTaskStatus
        task = AsyncTask(task_id='t-1', tool_name='x', arguments={}, delivery_type='file',
                         delivery_destination='r.json', status=AsyncTaskStatus.COMPLETED, result={'ok': 1})
        assert self._router(tmp_path).deliver(task)
        assert json.loads((tmp_path / 'r.json').read_text())['result'] == {'ok': 1}

    def test_webhook_needs_allowlist(self, tmp_path):
        from sajha.core.async_executor import DeliveryError
        with pytest.raises(DeliveryError):
            self._router(tmp_path).validate('webhook', 'https://hooks.example.com/x')
        router = self._router(tmp_path, ['https://hooks.example.com/sajha'])
        router.validate('webhook', 'https://hooks.example.com/sajha/task')
        for bad in ('https://hooks.example.com.evil.net/sajha/x', 'https://hooks.example.com/sajhaX',
                    'http://hooks.example.com/sajha/x', 'https://user:pw@hooks.example.com/sajha/x',
                    'file:///etc/passwd'):
            with pytest.raises(DeliveryError):
                router.validate('webhook', bad)

    @pytest.mark.parametrize('host', ['127.0.0.1', '10.1.2.3', '169.254.169.254', '::1', '::ffff:127.0.0.1'])
    def test_webhook_ssrf_guard(self, tmp_path, host):
        from sajha.core.async_executor import DeliveryError
        with pytest.raises(DeliveryError):
            self._router(tmp_path)._resolve_webhook_ip(host, 443)

    def test_private_networks_opt_in_never_allows_metadata(self, tmp_path):
        from sajha.core.async_executor import DeliveryError
        router = self._router(tmp_path, private=True)
        assert router._resolve_webhook_ip('10.1.2.3', 443) == '10.1.2.3'
        with pytest.raises(DeliveryError):
            router._resolve_webhook_ip('169.254.169.254', 80)

    def test_async_requires_permission(self, client, user_headers):
        r = client.post(f'/api/tools/{ALLOWED_TOOL}/execute-async', headers=user_headers,
                        json={**CI_ARGS, 'async': {'delivery': 'file', 'destination': 'r.json'}})
        assert r.status_code == 403

    def test_admin_traversal_rejected_at_submit(self, client, admin_headers):
        r = client.post(f'/api/tools/{ALLOWED_TOOL}/execute-async', headers=admin_headers,
                        json={**CI_ARGS, 'async': {'delivery': 'file', 'destination': '../../etc/x.json'}})
        assert r.status_code == 400
        r = client.post(f'/api/tools/{ALLOWED_TOOL}/execute-async', headers=admin_headers,
                        json={**CI_ARGS, 'async': {'delivery': 'webhook',
                                                   'destination': 'http://169.254.169.254/latest'}})
        assert r.status_code == 400


# ── 5. sensitive endpoints ───────────────────────────────────────

class TestSensitiveEndpoints:
    @pytest.mark.parametrize('method,path', [
        ('post', '/api/logging/setLevel'), ('get', '/api/ws/sessions'), ('get', '/api/replay/recent'),
        ('get', f'/api/replay/tool/{ALLOWED_TOOL}'), ('get', '/api/reports/users/activity'),
        ('post', '/api/admin/users/someone/password'),
    ])
    def test_anonymous_and_non_admin_refused(self, client, user_headers, method, path):
        kwargs = {'json': {'params': {'level': 'debug'}}} if method == 'post' else {}
        assert getattr(client, method)(path, **kwargs).status_code == 401
        assert getattr(client, method)(path, headers=user_headers, **kwargs).status_code == 403

    def test_admin_allowed(self, client, admin_headers):
        assert client.get('/api/ws/sessions', headers=admin_headers).status_code == 200
        r = client.post('/api/logging/setLevel', headers=admin_headers, json={'params': {'level': 'info'}})
        assert r.status_code == 200

    def test_tool_config_page_is_admin_only(self, client, user_headers):
        r = client.get(f'/tools/{ALLOWED_TOOL}/config', headers=user_headers)
        assert r.status_code == 403

    def test_shell_requires_admin(self, client, user_headers):
        assert client.post('/api/shell/python', headers=user_headers, json={'code': '1'}).status_code == 403


# ── 6. sign-in protection and passwords ──────────────────────────

class TestSignIn:
    def test_account_lockout(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_AUTH_LOGIN_MAX_FAILED_ATTEMPTS', '3')
        uid = _make_user('user')
        try:
            codes = [client.post('/api/auth/login', json={'user_id': uid, 'password': 'wrong-pass'}).status_code
                     for _ in range(3)]
            assert codes == [401, 401, 423]
            # locked: even the right password is refused
            r = client.post('/api/auth/login', json={'user_id': uid, 'password': GOOD_PASSWORD})
            assert r.status_code == 423
            r = client.post('/login', data={'user_id': uid, 'password': GOOD_PASSWORD}, follow_redirects=False)
            assert r.status_code == 423
        finally:
            _drop_user(uid)

    def test_success_resets_the_failure_count(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_AUTH_LOGIN_MAX_FAILED_ATTEMPTS', '3')
        uid = _make_user('user')
        try:
            for _ in range(2):
                client.post('/api/auth/login', json={'user_id': uid, 'password': 'wrong-pass'})
            _login(client, uid)
            for _ in range(2):
                assert client.post('/api/auth/login',
                                   json={'user_id': uid, 'password': 'wrong-pass'}).status_code == 401
        finally:
            _drop_user(uid)

    def test_ip_throttle(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_AUTH_LOGIN_IP_MAX_FAILURES', '2')
        for _ in range(2):
            client.post('/api/auth/login', json={'user_id': 'ghost-user', 'password': 'nope'})
        assert client.post('/api/auth/login', json={'user_id': 'ghost-user', 'password': 'x'}).status_code == 429
        r = client.post('/login', data={'user_id': 'ghost-user', 'password': 'x'}, follow_redirects=False)
        assert r.status_code == 429

    def test_successful_logins_are_not_throttled(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_AUTH_LOGIN_IP_MAX_FAILURES', '2')
        uid = _make_user('user')
        try:
            for _ in range(4):
                _login(client, uid)
        finally:
            _drop_user(uid)

    def test_change_password_flow_and_banner(self, client, admin_headers):
        uid = _make_user('user', must_change=True)
        try:
            r = client.post('/login', data={'user_id': uid, 'password': GOOD_PASSWORD}, follow_redirects=False)
            cookies = dict(r.cookies)
            client.cookies.clear()
            page = client.get('/dashboard', cookies=cookies)
            assert 'password-change-banner' in page.text
            assert client.get('/account/password', cookies=cookies).status_code == 200
            bad = client.post('/account/password', cookies=cookies, data={
                'current_password': GOOD_PASSWORD, 'new_password': 'admin123', 'confirm_password': 'admin123'})
            assert bad.status_code == 400
            ok = client.post('/account/password', cookies=cookies, data={
                'current_password': GOOD_PASSWORD, 'new_password': 'Brand-New-Pass-2',
                'confirm_password': 'Brand-New-Pass-2'})
            assert ok.status_code == 200 and 'has been changed' in ok.text
            new_cookies = dict(ok.cookies)
            client.cookies.clear()
            assert 'password-change-banner' not in client.get('/dashboard', cookies=new_cookies).text
            r = client.post('/api/auth/login', json={'user_id': uid, 'password': 'Brand-New-Pass-2'})
            assert r.status_code == 200 and r.json()['password_change_required'] is False
            # admin reset -> must change again
            r = client.post(f'/api/admin/users/{uid}/password', headers=admin_headers,
                            json={'password': 'Reset-By-Admin-3'})
            assert r.status_code == 200
            r = client.post('/api/auth/login', json={'user_id': uid, 'password': 'Reset-By-Admin-3'})
            assert r.json()['password_change_required'] is True
            hdrs = {'Authorization': f"Bearer {r.json()['token']}"}
            r = client.post('/api/auth/change-password', headers=hdrs,
                            json={'current_password': 'Reset-By-Admin-3', 'new_password': 'Mine-Again-4'})
            assert r.status_code == 200 and r.json()['token']
        finally:
            client.cookies.clear()
            _drop_user(uid)

    def test_default_password_sets_the_flag(self, client, admin_headers):
        r = client.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'})
        assert r.json()['password_change_required'] is True

    def test_password_policy(self):
        from sajha.auth.password import password_problem
        assert password_problem('short', 'u')
        assert password_problem('admin123', 'u')
        assert password_problem('someuser1', 'someuser1')
        assert password_problem('x' * 73, 'u')
        assert password_problem(GOOD_PASSWORD, 'u') is None

    def test_admin_create_user_requires_a_password(self, client, admin_headers):
        r = client.post('/api/admin/users/create', headers=admin_headers,
                        json={'user_id': f'hard_nopw_{uuid.uuid4().hex[:6]}'})
        assert r.status_code == 400

    def test_verify_password_with_invalid_hash_logs_instead_of_crashing(self):
        from sajha.auth.password import verify_password
        assert verify_password('x', 'not-a-bcrypt-hash') is False


# ── 7. API key tool lists ────────────────────────────────────────

class TestApiKeyToolAccess:
    def test_allowlist_on_rest_mcp_and_a2a(self, client):
        key = {'X-API-Key': _api_key('allowlist', ['calc_compound_*'])}
        r = client.post('/api/tools/execute', headers=key, json={'tool': ALLOWED_TOOL, 'arguments': CI_ARGS})
        assert r.status_code == 200, r.text
        r = client.post('/api/tools/execute', headers=key, json={'tool': OTHER_TOOL, 'arguments': {}})
        assert r.status_code == 403
        assert _names(legacy(client, 'tools/list', headers=key)) == {ALLOWED_TOOL}
        assert _names(modern(client, 'tools/list', headers=key)) == {ALLOWED_TOOL}
        r = modern(client, 'tools/call', {'name': OTHER_TOOL, 'arguments': {}}, headers=key).json()
        assert r['error']['code'] == -32010
        res = client.post('/a2a', headers=key, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'tasks/send',
            'params': {'message': {'parts': [{'type': 'text', 'text': f'run {OTHER_TOOL}'}]}}}).json()
        assert 'Access denied' in json.dumps(res)

    def test_denylist(self, client):
        key = {'X-API-Key': _api_key('denylist', [OTHER_TOOL])}
        names = _names(legacy(client, 'tools/list', headers=key))
        assert ALLOWED_TOOL in names and OTHER_TOOL not in names
        r = client.post('/api/tools/execute', headers=key, json={'tool': OTHER_TOOL, 'arguments': {}})
        assert r.status_code == 403

    def test_mode_all_executes(self, client):
        key = {'X-API-Key': _api_key('all', [])}
        r = client.post('/api/tools/execute', headers=key, json={'tool': ALLOWED_TOOL, 'arguments': CI_ARGS})
        assert r.status_code == 200, r.text

    def test_policy_units(self):
        from sajha.auth.access import apikey_policy
        assert apikey_policy('regex', ['calc_(capm|beta)']).can_execute('calc_capm')
        assert not apikey_policy('regex', ['calc_(capm|beta)']).can_execute('calc_capm_x')
        assert not apikey_policy('bogus', ['*']).can_execute('calc_capm')


# ── 9. configuration ─────────────────────────────────────────────

class TestConfigFixes:
    def test_async_and_shell_settings_are_real_fields(self):
        from sajha.core.config import Settings
        for f in ('async_enabled', 'async_workers', 'async_queue_size', 'async_task_ttl_hours',
                  'async_file_base_dir', 'shell_enabled', 'shell_bash_enabled', 'shell_python_timeout'):
            assert f in Settings.model_fields, f

    def test_async_env_override_is_honoured(self, monkeypatch):
        from sajha.core.config import Settings
        monkeypatch.setenv('SAJHA_ASYNC_WORKERS', '3')
        assert Settings().async_workers == 3

    def test_bool_parsing(self):
        from sajha.core.config import cfg_bool, parse_bool
        cfg = {'a': 'false', 'b': 'True', 'c': '0', 'd': 'yes'}
        assert [cfg_bool(cfg, k) for k in 'abcd'] == [False, True, False, True]
        assert cfg_bool(cfg, 'missing', True) is True
        assert parse_bool('off', True) is False

    def test_unknown_dotenv_names_do_not_stop_startup(self, tmp_path, monkeypatch):
        from sajha.core.config import Settings, unknown_sajha_env_names
        env = tmp_path / '.env'
        env.write_text('FMP_API_KEY=abc\nSAJHA_NOT_A_SETTING=1\nSAJHA_MCP_AUTH_MODE=optional\n')
        Settings(_env_file=str(env))
        assert unknown_sajha_env_names(['SAJHA_NOT_A_SETTING', 'SAJHA_SERVER_PORT', 'FMP_API_KEY']) == \
            ['SAJHA_NOT_A_SETTING']

    def test_storage_env_overrides_yaml(self, monkeypatch):
        from sajha.core.storage import storage_setting
        cfg = {'storage.backend': 'local', 'storage.s3.bucket': '', 'storage.azure.connection_string': ''}
        assert storage_setting(cfg, 'storage.backend') == 'local'
        monkeypatch.setenv('SAJHA_STORAGE_BACKEND', 's3')
        monkeypatch.setenv('SAJHA_S3_BUCKET', 'bkt')
        monkeypatch.setenv('AZURE_STORAGE_CONNECTION_STRING', 'cs')
        assert storage_setting(cfg, 'storage.backend') == 's3'
        assert storage_setting(cfg, 'storage.s3.bucket') == 'bkt'
        assert storage_setting(cfg, 'storage.azure.connection_string') == 'cs'
        monkeypatch.setenv('SAJHA_STORAGE_S3_PREFIX', 'p/')
        assert storage_setting(cfg, 'storage.s3.prefix') == 'p/'

    def test_alpha_vantage_key_is_defined(self):
        from sajha.core.config import _CFG
        assert 'alpha_vantage.api.key' in _CFG


# ── 10. nginx ────────────────────────────────────────────────────

def test_nginx_does_not_buffer_mcp_streams():
    text = Path('deployment/baremetal/nginx.conf').read_text()
    start = text.index('location ~ ^/(api/)?mcp/?$')
    block = text[start:text.index('}', start)]
    for directive in ('proxy_buffering off', 'proxy_cache off', 'proxy_read_timeout', 'proxy_http_version 1.1'):
        assert directive in block
    assert 'add_header' not in block      # would drop the server-level security headers


# ── auth error responses and schema migration ────────────────────

class TestAuthErrorsAndSchema:
    def test_api_and_json_requests_get_json_401(self, client):
        client.cookies.clear()
        for method, path, headers in (('post', '/admin/studio/rest/preview', {}),
                                      ('get', '/api/ws/sessions', {}),
                                      ('get', '/dashboard', {'Accept': 'application/json'}),
                                      ('post', '/account/password', {})):
            r = getattr(client, method)(path, headers=headers, follow_redirects=False)
            assert r.status_code == 401, (path, r.status_code)
            assert r.json()['error'] == 'Authentication required'

    def test_browser_navigation_still_redirects(self, client):
        client.cookies.clear()
        r = client.get('/dashboard', headers={'Accept': 'text/html,application/xhtml+xml'},
                       follow_redirects=False)
        assert r.status_code == 302 and r.headers['location'] == '/'

    def test_api_403_is_json(self, client, user_headers):
        r = client.get('/api/ws/sessions', headers=user_headers)
        assert r.status_code == 403 and 'error' in r.json()

    def test_missing_column_is_added_at_startup(self, tmp_path):
        from sqlalchemy import create_engine, inspect, text
        from sajha.db import engine as eng
        url = f'sqlite:///{tmp_path / "old.db"}'
        old = create_engine(url)
        with old.begin() as c:
            c.execute(text('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(100))'))
        saved = eng._engine
        try:
            eng._engine = old
            eng._ensure_columns()
            eng._ensure_columns()          # idempotent
        finally:
            eng._engine = saved
        assert 'must_change_password' in {c['name'] for c in inspect(old).get_columns('users')}

    def test_schema_scripts_declare_the_column(self):
        for d in ('sqlite', 'postgresql'):
            assert 'must_change_password' in Path(f'db/scripts/{d}/001_schema.sql').read_text()


# The REST mirrors of three MCP methods had no auth check at all.
@pytest.mark.parametrize('path', ['/api/resources/list', '/api/resources/read',
                                  '/api/completion/complete'])
def test_rest_mirrors_of_mcp_methods_require_sign_in(web, path):
    c, admin = web
    assert c.post(path, json={'params': {}}).status_code == 401
    assert c.post(path, json={'params': {}}, cookies=admin).status_code != 401
