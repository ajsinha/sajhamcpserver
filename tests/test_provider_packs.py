# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Provider packs (sajha/packs): the pack format, the bundled packs (GitHub, Slack, Box) and their
licences, the plan and its review hash, the install gate (approval, hash, plan errors, policy), the
provider preset seen by the connected-accounts registry, and a whole install against fake endpoints:
a pack whose OAuth server runs in process and whose API is a local HTTP server, linked by a user
through the real authorization-code flow and called through the deployed tool as that user.

Design: docs/architecture/Connected Accounts.md §11
"""

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parent.parent
SECRET = 'pack-client-secret-0123456789'
KEY = 'test-vault-key-packs-' + 'z' * 32
AUTH = 'https://auth.fakepack.test'


# ── fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    """Tool configs, import records, presets and pack records land in tmp_path."""
    import sajha.core.storage as storage
    from sajha.accounts import presets
    from sajha.accounts.providers import set_registry
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path / 'store')))
    monkeypatch.setenv('SAJHA_API_IMPORT_ALLOW_LOCALHOST', 'true')
    monkeypatch.setenv('SAJHA_ACCOUNTS_PROVIDERS', '{}')        # no YAML providers: the presets alone
    presets.invalidate()
    set_registry(None)
    yield tmp_path
    presets.invalidate()
    set_registry(None)


class FakeRegistry:
    """The registry surface API Import uses."""

    def __init__(self):
        self.tools, self.tool_configs, self.tool_errors, self._file_timestamps = {}, {}, {}, {}
        self._tools_lock = threading.RLock()

    def _config_rel(self, ref):
        s = str(ref)
        if s.startswith('config/tools/'):
            return s
        from sajha.tools.tool_files import get_index
        return get_index('config/tools').target_path(Path(s).stem, '')

    def load_tool_from_config(self, ref):
        from sajha.api_import.executor import ImportedAPITool
        from sajha.core.storage import get_storage
        cfg = get_storage().read_json(self._config_rel(ref))
        self.tool_configs[cfg['name']] = cfg
        self.tools[cfg['name']] = ImportedAPITool(cfg)

    def unregister_tool(self, name):
        self.tools.pop(name, None)


class Admin:
    user_id, roles, auth_type, is_admin = 'root', ['admin'], 'session', True


# ── a fake service: OAuth server in process, API on a local port ──────

class FakeAPI:
    def __init__(self):
        self.calls = []


def _api_handler(api):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, status, body):
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _handle(self):
            u = urlsplit(self.path)
            n = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(n) if n else b''
            auth = self.headers.get('Authorization', '')
            api.calls.append((self.command, u.path, auth, body))
            if not auth.startswith('Bearer at-'):
                return self._send(401, {'message': 'no token'})
            user = auth[len('Bearer at-'):]
            if u.path == '/v1/me':
                return self._send(200, {'login': user, 'id': 7})
            if u.path == '/v1/notes' and self.command == 'POST':
                return self._send(201, {'id': 1, 'text': json.loads(body)['text'], 'owner': user})
            return self._send(404, {'message': 'nope'})
        do_GET = do_POST = _handle
    return H


@pytest.fixture(scope='module')
def fake_api():
    api = FakeAPI()
    server = ThreadingHTTPServer(('127.0.0.1', 0), _api_handler(api))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api.url = f'http://127.0.0.1:{server.server_address[1]}'
    yield api
    server.shutdown()


class FakeOAuth:
    """Authorize + token endpoints of the fake service (an httpx transport for sajha.accounts.http)."""

    def __init__(self):
        self.codes = {}

    def approve(self, authorize_url, login):
        q = {k: v[0] for k, v in parse_qs(urlsplit(authorize_url).query).items()}
        code = f'code-{login}'
        self.codes[code] = (login, q.get('scope', ''), q['redirect_uri'])
        return {'state': q['state'], 'code': code}

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        if url.path == '/token':
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if form.get('client_secret') != SECRET or form.get('client_id') != 'pack-client':
                return httpx.Response(401, json={'error': 'invalid_client'})
            login, scope, redirect = self.codes.pop(form.get('code'), (None, None, None))
            if login is None or redirect != form.get('redirect_uri'):
                return httpx.Response(400, json={'error': 'invalid_grant'})
            return httpx.Response(200, json={'access_token': f'at-{login}', 'refresh_token': f'rt-{login}',
                                             'token_type': 'bearer', 'expires_in': 3600, 'scope': scope})
        return httpx.Response(404, json={})


SPEC = {
    'openapi': '3.0.3', 'info': {'title': 'Notes', 'version': '1'},
    'components': {'securitySchemes': {'notesAuth': {'type': 'oauth2', 'flows': {'authorizationCode': {
        'authorizationUrl': f'{AUTH}/authorize', 'tokenUrl': f'{AUTH}/token', 'scopes': {'notes': 'notes'}}}}}},
    'security': [{'notesAuth': ['notes']}],
    'paths': {
        '/v1/me': {'get': {'operationId': 'me', 'summary': 'Who am I',
                           'responses': {'200': {'description': 'ok', 'content': {'application/json': {
                               'schema': {'type': 'object'}}}}}}},
        '/v1/notes': {'post': {'operationId': 'create_note', 'summary': 'Create a note',
                               'requestBody': {'required': True, 'content': {'application/json': {'schema': {
                                   'type': 'object', 'required': ['text'],
                                   'properties': {'text': {'type': 'string'}}}}}},
                               'responses': {'201': {'description': 'made'}}},
                      'delete': {'operationId': 'purge_notes', 'summary': 'Delete every note',
                                 'responses': {'204': {'description': 'gone'}}}},
    },
}


def write_pack(root: Path, base_url: str, pid='notes', **over) -> Path:
    folder = root / 'packs' / pid
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(SPEC, indent=1)
    (folder / 'openapi.json').write_text(text, encoding='utf-8')
    (folder / 'LICENSE').write_text('MIT License\n\nCopyright (c) test\n', encoding='utf-8')
    manifest = {
        'format': 1, 'id': pid, 'title': 'Notes', 'version': '1.0.0', 'description': 'Notes as you.',
        'provider': {'id': f'{pid}svc', 'template': '', 'title': 'Notes service',
                     'authorize_url': f'{AUTH}/authorize', 'token_url': f'{AUTH}/token', 'revoke_style': 'none',
                     'userinfo_url': '', 'scopes': ['notes'], 'pkce': True, 'api_hosts': ['127.0.0.1']},
        'api': {'spec': 'openapi.json', 'spec_sha256': hashlib.sha256(text.encode()).hexdigest(),
                'prefix': pid, 'base_url': base_url, 'security_scheme': 'notesAuth', 'scopes': ['notes'],
                'operations': ['GET /v1/me', 'POST /v1/notes']},
        'source': {'url': 'https://example.test/notes-spec', 'licence': 'MIT', 'licence_file': 'LICENSE'},
    }
    for k, v in over.items():
        manifest[k] = v
    (folder / 'pack.json').write_text(json.dumps(manifest), encoding='utf-8')
    return folder


INPUTS = {'client_id': 'pack-client', 'client_secret_ref': 'env:NOTES_PACK_SECRET'}


# ── the format ──────────────────────────────────────────────────────

def test_bundled_packs_parse_with_permissive_licences_and_matching_specs():
    from sajha.packs.manifest import PERMISSIVE_LICENCES, discover
    packs, problems = discover()
    assert problems == {}
    assert {'github', 'slack', 'box'} <= set(packs)
    for pack in packs.values():
        assert pack.source['licence'] in PERMISSIVE_LICENCES and pack.licence_text.strip()
        assert pack.api['spec_sha256'] == hashlib.sha256(pack.spec_text.encode()).hexdigest()
        assert pack.source.get('revision') and pack.source.get('changes')
        # the spec itself says where it came from and that it was trimmed
        assert pack.source['url'] in json.loads(pack.spec_text)['info']['description']


@pytest.mark.parametrize('field,value,msg', [
    ('provider', {'client_id': 'x', 'authorize_url': 'https://a'}, 'may not set client_id'),
    ('source', {'url': 'https://x', 'licence': 'Proprietary', 'licence_file': 'LICENSE'}, 'not one SAJHA bundles'),
    ('api', {'spec': '../etc/passwd', 'prefix': 'np', 'base_url': 'https://x', 'operations': ['GET /a']},
     'a file name in the pack folder'),
    ('api', {'spec': 'openapi.json', 'prefix': 'np', 'base_url': 'https://x', 'operations': ['fetch everything']},
     'METHOD /path'),
])
def test_manifest_problems_are_refused(tmp_path, field, value, msg):
    from sajha.packs.manifest import PackError, load
    folder = write_pack(tmp_path, 'https://api.example.test', **{field: value})
    with pytest.raises(PackError, match=msg):
        load(folder)


def test_tampered_spec_fails_the_checksum(tmp_path):
    from sajha.packs.manifest import PackError, load
    folder = write_pack(tmp_path, 'https://api.example.test')
    (folder / 'openapi.json').write_text(json.dumps({**SPEC, 'servers': [{'url': 'https://evil.test'}]}))
    with pytest.raises(PackError, match='spec_sha256'):
        load(folder)


# ── the plan ────────────────────────────────────────────────────────

@pytest.mark.parametrize('pack_id,count', [('github', 6), ('slack', 4), ('box', 5)])
def test_bundled_packs_plan_without_errors(store_dir, pack_id, count):
    from sajha.packs import service
    p = service.plan(pack_id, {'client_id': 'cid', 'client_secret_ref': 'env:X'}, FakeRegistry(), Admin())
    assert p['errors'] == [], p['errors']
    assert len(p['api']['operations']) == count and all(o['status'] == 'new' for o in p['api']['operations'])
    assert p['provider']['configured'] and p['provider']['redirect_uri'].endswith(f'/{pack_id}/callback')
    binding = next(iter(p['api']['binding'].values()))
    assert binding['type'] == 'connected_account' and binding['provider'] == pack_id
    assert len(p['hash']) == 64


def test_the_plans_redirect_uri_uses_the_same_base_as_the_connect_flow(store_dir, monkeypatch):
    # accounts.public_url unset: the request's base URL over HTTP, else the port this server listens on
    from sajha.accounts.settings import AccountsSettings, set_accounts_settings
    from sajha.core import transport
    from sajha.packs import service
    set_accounts_settings(AccountsSettings(public_url=''))
    try:
        class Req:
            base_url = 'http://sajha.internal:5555/'
        inputs = {'client_id': 'cid', 'client_secret_ref': 'env:X'}
        p = service.plan('github', inputs, FakeRegistry(), Admin(), request=Req())
        assert p['provider']['redirect_uri'] == 'http://sajha.internal:5555/account/connections/github/callback'
        monkeypatch.setattr(transport, '_listening_port', 4317)
        p2 = service.plan('github', inputs, FakeRegistry(), Admin())
        assert p2['provider']['redirect_uri'].endswith(':4317/account/connections/github/callback')
        assert p2['hash'] == p['hash']                   # the redirect URI is not part of the review
    finally:
        set_accounts_settings(None)


def test_links_without_a_request_use_the_listening_port(monkeypatch):
    from sajha.accounts.service import ConnectedAccountsService
    from sajha.accounts.settings import AccountsSettings, base_url, set_accounts_settings
    from sajha.core import transport
    set_accounts_settings(AccountsSettings(public_url=''))
    try:
        monkeypatch.setattr(transport, '_listening_port', None)
        transport.note_listening({'type': 'http', 'server': ('testserver', 80)})     # TestClient: ignored
        assert transport._listening_port is None
        transport.note_listening({'type': 'http', 'server': ('127.0.0.1', 3197)})
        transport.note_listening({'type': 'http', 'server': ('127.0.0.1', 9999)})    # the first one counts
        assert transport._listening_port == 3197
        assert base_url().endswith(':3197')
        assert ConnectedAccountsService().connect_url('github').endswith(':3197/account/connections?connect=github')
        set_accounts_settings(AccountsSettings(public_url='https://sajha.example'))
        assert base_url() == 'https://sajha.example'      # a configured origin still wins
    finally:
        set_accounts_settings(None)


def test_plan_without_a_client_id_is_an_error_and_secrets_must_be_references(store_dir):
    from sajha.packs import service
    from sajha.packs.manifest import PackError
    p = service.plan('box', {}, FakeRegistry(), Admin())
    assert any('no client id' in e for e in p['errors'])
    with pytest.raises(PackError, match='never the secret'):
        service.plan('box', {'client_id': 'c', 'client_secret_ref': 'hunter2'}, FakeRegistry(), Admin())
    with pytest.raises(PackError, match='never the secret'):
        service.plan('box', {'client_id': 'c', 'client_secret': 'hunter2'}, FakeRegistry(), Admin())


def test_a_base_url_off_the_providers_api_hosts_is_refused(store_dir):
    from sajha.packs import service
    write_pack(store_dir, 'https://elsewhere.example.test')
    p = service.plan('notes', INPUTS, FakeRegistry(), Admin(), dirs=[str(store_dir / 'packs')])
    assert any("user's token may not go there" in e for e in p['errors'])


def test_hash_moves_with_inputs_and_pack_contents(store_dir, fake_api):
    from sajha.packs import service
    dirs = [str(write_pack(store_dir, fake_api.url).parent)]
    a = service.plan('notes', INPUTS, FakeRegistry(), Admin(), dirs=dirs)['hash']
    assert service.plan('notes', INPUTS, FakeRegistry(), Admin(), dirs=dirs)['hash'] == a
    assert service.plan('notes', {**INPUTS, 'client_id': 'other'}, FakeRegistry(), Admin(), dirs=dirs)['hash'] != a
    write_pack(store_dir, fake_api.url, version='1.0.1')
    assert service.plan('notes', INPUTS, FakeRegistry(), Admin(), dirs=dirs)['hash'] != a


# ── the gate ────────────────────────────────────────────────────────

def test_install_needs_approval_the_reviewed_hash_and_no_errors(store_dir, fake_api):
    from sajha.packs import service
    from sajha.packs.manifest import PackError
    dirs = [str(write_pack(store_dir, fake_api.url).parent)]
    reg = FakeRegistry()
    h = service.plan('notes', INPUTS, reg, Admin(), dirs=dirs)['hash']
    with pytest.raises(PackError, match='explicit approval'):
        service.install('notes', INPUTS, h, False, reg, Admin(), dirs=dirs)
    with pytest.raises(PackError, match='changed since you reviewed') as e:
        service.install('notes', INPUTS, 'f' * 64, True, reg, Admin(), dirs=dirs)
    assert e.value.status == 409 and e.value.extra['hash'] == h
    with pytest.raises(PackError, match='plan has errors'):
        service.install('notes', {}, h, True, reg, Admin(), dirs=dirs)
    assert reg.tools == {}


def test_policy_deny_and_require_approval_stop_the_install(store_dir, fake_api, monkeypatch):
    from sajha.packs import service
    from sajha.packs.manifest import PackError
    from sajha.studio import describe
    dirs = [str(write_pack(store_dir, fake_api.url).parent)]
    reg = FakeRegistry()
    h = service.plan('notes', INPUTS, reg, Admin(), dirs=dirs)['hash']
    seen = {}

    def gate(p, user):
        seen.update(p)
        raise describe.DescribeError('policy rule r1 requires a second approval', 409, approval_id='ap1', rule='r1')
    monkeypatch.setattr(describe, '_policy_gate', gate)
    with pytest.raises(PackError) as e:
        service.install('notes', INPUTS, h, True, reg, Admin(), dirs=dirs)
    assert e.value.status == 409 and e.value.extra['approval_id'] == 'ap1'
    assert seen == {'name': 'pack:notes', 'kind': 'pack'}
    assert reg.tools == {} and service.load_record('notes') is None


# ── a whole install against fake endpoints ──────────────────────────

@pytest.fixture
def accounts(store_dir, tmp_path, monkeypatch):
    """The connected-accounts service over a temporary vault, using the global (preset-loaded) registry."""
    from sajha.accounts import http as ahttp
    from sajha.accounts.service import ConnectedAccountsService, set_service
    from sajha.accounts.settings import AccountsSettings, set_accounts_settings
    from sajha.accounts.vault import LocalKeyProvider, TokenVault, set_vault
    from sajha.core.state.memory import MemoryStateStore
    monkeypatch.setenv('NOTES_PACK_SECRET', SECRET)
    oauth = FakeOAuth()
    ahttp.set_transport(httpx.MockTransport(oauth.handler))
    set_accounts_settings(AccountsSettings(public_url='https://sajha.test'))
    vault = TokenVault(engine=create_engine(f'sqlite:///{tmp_path / "vault.db"}'), key_provider=LocalKeyProvider(KEY))
    set_vault(vault)
    svc = ConnectedAccountsService(None, vault, MemoryStateStore('p:'))
    monkeypatch.setattr(ConnectedAccountsService, 'audit', staticmethod(lambda *a, **k: None))
    set_service(svc)
    yield oauth, svc
    ahttp.set_transport(None)
    set_service(None)
    set_vault(None)
    set_accounts_settings(None)


def test_install_link_and_call_as_the_user_then_uninstall(store_dir, fake_api, accounts):
    from sajha.accounts.injection import bind
    from sajha.accounts.providers import get_registry
    from sajha.observability.caller import Caller, reset, set_caller
    from sajha.packs import service
    oauth, svc = accounts
    dirs = [str(write_pack(store_dir, fake_api.url).parent)]
    reg = FakeRegistry()
    assert get_registry().get('notessvc') is None

    plan = service.plan('notes', INPUTS, reg, Admin(), dirs=dirs)
    assert plan['errors'] == [] and [o['name'] for o in plan['api']['operations']] == ['notes_me', 'notes_create_note']
    assert plan['provider']['redirect_uri'] == 'https://sajha.test/account/connections/notessvc/callback'
    out = service.install('notes', INPUTS, plan['hash'], True, reg, Admin(), dirs=dirs)
    assert out['success'] and out['record']['tools'] == ['notes_create_note', 'notes_me']
    assert set(reg.tools) == {'notes_me', 'notes_create_note'}          # the DELETE was not in the reviewed selection
    cfg = reg.tool_configs['notes_create_note']
    assert cfg['auth'] == {'connected_account': 'notessvc', 'scopes': ['notes']}
    assert 'client_secret' not in json.dumps(cfg) and SECRET not in json.dumps(cfg)

    # the preset is a provider of the registry now, configured from the install inputs
    p = get_registry().get('notessvc')
    assert p is not None and p.configured and p.client_id == 'pack-client' and p.api_hosts == ['127.0.0.1']

    # alice links her account through the real authorization-code flow (PKCE) ...
    url = svc.start('alice', 'notessvc', browser_nonce='n-a')
    assert url.startswith(f'{AUTH}/authorize?') and 'code_challenge=' in url
    back = oauth.approve(url, 'alice')
    svc.complete('alice', 'notessvc', state=back['state'], code=back['code'], browser_nonce='n-a')

    # ... and the deployed tool calls the API with her token, not anyone else's
    tool = reg.tools['notes_create_note']
    token = set_caller(Caller('alice'))
    try:
        with bind(tool, {'body': {'text': 'hi'}}):
            result = tool.execute({'body': {'text': 'hi'}})
    finally:
        reset(token)
    assert result['status'] == 201 and result['body'] == {'id': 1, 'text': 'hi', 'owner': 'alice'}
    assert fake_api.calls[-1][:3] == ('POST', '/v1/notes', 'Bearer at-alice')

    # bob has no link: the tool asks him to connect instead of calling
    from sajha.accounts.errors import ConnectedAccountRequired
    token = set_caller(Caller('bob'))
    try:
        with pytest.raises(ConnectedAccountRequired):
            with bind(reg.tools['notes_me'], {}):
                pass
    finally:
        reset(token)

    # installing the same plan again needs a new review (statuses moved from new to unchanged)
    again = service.plan('notes', INPUTS, reg, Admin(), dirs=dirs)
    assert again['reinstall'] and again['hash'] != plan['hash']
    assert {o['status'] for o in again['api']['operations']} == {'unchanged'}

    gone = service.uninstall('notes', reg, Admin())
    assert sorted(gone['removed']) == ['notes_create_note', 'notes_me'] and gone['preset_removed']
    assert reg.tools == {} and get_registry().get('notessvc') is None and service.load_record('notes') is None


def test_a_failed_deploy_restores_the_previous_preset(store_dir, fake_api, monkeypatch):
    from sajha.accounts import presets
    from sajha.api_import import service as api_import
    from sajha.packs import service
    from sajha.packs.manifest import PackError
    monkeypatch.setenv('NOTES_PACK_SECRET', SECRET)
    dirs = [str(write_pack(store_dir, fake_api.url).parent)]
    reg = FakeRegistry()
    h = service.plan('notes', INPUTS, reg, Admin(), dirs=dirs)['hash']

    def boom(*a, **k):
        raise api_import.APIImportError('disk full')
    monkeypatch.setattr(api_import, 'deploy', boom)
    with pytest.raises(PackError, match='nothing was installed'):
        service.install('notes', INPUTS, h, True, reg, Admin(), dirs=dirs)
    assert presets.load('notessvc') is None and service.load_record('notes') is None


def test_yaml_configuration_overrides_the_preset(store_dir, fake_api, monkeypatch):
    from sajha.accounts import presets
    from sajha.accounts.providers import get_registry, set_registry
    presets.save('notessvc', {'template': '', 'authorize_url': f'{AUTH}/authorize', 'token_url': f'{AUTH}/token',
                              'scopes': ['notes'], 'api_hosts': ['127.0.0.1'], 'client_id': 'from-preset',
                              'client_secret_ref': 'env:A'}, pack='notes')
    monkeypatch.setenv('SAJHA_ACCOUNTS_PROVIDERS', json.dumps({'notessvc': {'client_id': 'from-yaml'}}))
    set_registry(None)
    assert get_registry().get('notessvc').client_id == 'from-yaml'


def test_registry_reloads_when_another_worker_saves_a_preset(store_dir, monkeypatch):
    from sajha.accounts import presets
    from sajha.accounts.providers import get_registry
    first = get_registry()
    assert first.get('notessvc') is None
    # another worker writes the preset file: this process notices once its cached stamp expires
    from sajha.core.storage import get_storage
    get_storage().write_json(f'{presets.PRESETS_DIR}/notessvc.json', {
        'provider': 'notessvc', 'pack': 'notes', 'fields': {
            'template': '', 'authorize_url': f'{AUTH}/authorize', 'token_url': f'{AUTH}/token',
            'scopes': ['notes'], 'api_hosts': ['127.0.0.1'], 'client_id': 'c', 'client_secret_ref': 'env:A'}})
    monkeypatch.setattr(presets, 'STAMP_TTL', 0.0)
    assert get_registry() is not first and get_registry().get('notessvc').configured


# ── the CLI and the admin API ───────────────────────────────────────

def test_cli_plan_and_install(store_dir, fake_api, capsys, monkeypatch):
    from sajha.packs import __main__ as cli
    from sajha.packs import manifest
    monkeypatch.setenv('NOTES_PACK_SECRET', SECRET)
    write_pack(store_dir, fake_api.url)
    monkeypatch.setattr(manifest, 'bundled_dir', lambda: store_dir / 'packs')
    monkeypatch.setattr(cli, '_ensure_db', lambda: None)
    args = ['notes', '--client-id', 'pack-client', '--client-secret-ref', 'env:NOTES_PACK_SECRET']
    assert cli.main(['plan'] + args) == 0
    shown = capsys.readouterr().out
    h = shown.rsplit('review hash: ', 1)[1].strip()
    assert 'notes_create_note' in shown and 'register this redirect URI' in shown
    assert cli.main(['install'] + args + ['--hash', h]) == 1                  # no --approve
    assert cli.main(['install'] + args + ['--hash', h, '--approve']) == 0
    assert 'Installed Notes' in capsys.readouterr().out
    assert cli.main(['list']) == 0 and 'installed 1.0.0' in capsys.readouterr().out
    assert cli.main(['uninstall', 'notes']) == 0


def test_admin_api_is_admin_only_and_checks_csrf_for_sessions():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sajha.auth import AuthContext, require_admin
    from sajha.routes import packs_routes
    app = FastAPI()
    app.include_router(packs_routes.router)
    app.dependency_overrides[require_admin] = lambda: AuthContext(user_id='root', user_name='root', roles=['admin'],
                                                                  auth_type='session')
    c = TestClient(app)
    r = c.get('/api/admin/packs')
    assert r.status_code == 200 and {p['id'] for p in r.json()['packs']} >= {'github', 'slack', 'box'}
    r = c.get('/api/admin/packs/box')
    assert r.status_code == 200 and 'Apache License' in r.json()['licence']
    assert c.get('/api/admin/packs/nope').status_code == 404
    c.cookies.set('sajha_token', 'session-cookie')
    r = c.post('/api/admin/packs/box/plan', json={})
    assert r.status_code == 403 and 'CSRF' in r.json()['error']
