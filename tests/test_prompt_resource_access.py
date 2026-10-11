# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Per-caller access to prompts and data resources (Roadmap X3, sajha/auth/access.py):

* an API key whose tool access is ``allowlist`` or ``regex`` reaches only the prompts and data
  resources it is granted (``prompt:`` / ``resource:`` entries); ``all`` and ``denylist`` keys
  are not limited unless they carry such entries;
* roles limit through ``permissions`` rows of resource_type ``prompt`` / ``resource``; a role
  without such rows grants everything (the behaviour before);
* the same rule on MCP 2025-11-25 and 2026-07-28, the REST endpoints and the console pages;
* federated prompts and resources follow it by their namespaced names and URIs.
"""
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

PROMPT = 'bug_diagnosis'
DATA = 'sajha://data/customers.csv'
OTHER_DATA = 'sajha://data/orders.csv'
PASSWORD = 'Prompt-Access-Pass-1'
META = {'io.modelcontextprotocol/protocolVersion': '2026-07-28',
        'io.modelcontextprotocol/clientCapabilities': {},
        'io.modelcontextprotocol/clientInfo': {'name': 'pytest', 'version': '1'}}
ARGS = {'bug_description': 'x', 'error_message': 'e', 'code': 'c', 'language': 'py'}


# ── the rule itself ─────────────────────────────────────────────────

def test_split_access_list_keeps_tool_patterns_apart():
    from sajha.auth.access import split_access_list, apikey_policy
    tools, prompts, resources = split_access_list(['calc_*', 'prompt:bug_*', 'resource:sajha://data/*.csv'])
    assert (tools, prompts, resources) == (['calc_*'], ['bug_*'], ['sajha://data/*.csv'])
    policy = apikey_policy('allowlist', '["calc_*", "prompt:bug_*"]')
    assert policy.can_execute('calc_add') and not policy.can_see('prompt:bug_diagnosis')


@pytest.mark.parametrize('mode,entries,expected', [
    ('all', [], (None, None)),
    ('denylist', ['wiki_*'], (None, None)),
    ('allowlist', ['calc_*'], ([], [])),
    ('regex', ['calc_.*'], ([], [])),
    ('allowlist', ['calc_*', 'prompt:bug_*'], (['bug_*'], [])),
    ('all', ['resource:sajha://data/x.csv'], (None, ['sajha://data/x.csv'])),
])
def test_apikey_catalog_rules(mode, entries, expected):
    from sajha.auth.access import apikey_catalog_rules
    assert apikey_catalog_rules(mode, entries) == expected


def _role(*rows):
    return SimpleNamespace(permissions=[SimpleNamespace(resource_type=t, resource_name=n, actions='read')
                                        for t, n in rows])


def test_role_patterns_union_and_default():
    from sajha.auth.access import _role_catalog_patterns as pats
    limited = _role(('tool', '*'), ('prompt', 'bug_*'))
    assert pats([limited], 'prompt') == ['bug_*']
    assert pats([limited], 'resource') is None                    # no resource rows: everything
    assert pats([limited, _role(('tool', '*'))], 'prompt') is None   # another role grants all
    assert pats([limited, _role(('prompt', 'code_*'))], 'prompt') == ['bug_*', 'code_*']
    assert pats([], 'prompt') is None


def test_session_rules_and_federated_names():
    from sajha.auth.access import can_see_prompt, can_read_resource
    session = {'user_id': 'u', 'authenticated': True, 'prompt_rules': [['bug_*', 'fed__*']],
               'resource_rules': [['sajha-federation://up/*']]}
    assert can_see_prompt(session, PROMPT) and can_see_prompt(session, 'fed__summarise')
    assert not can_see_prompt(session, 'code_review')
    assert can_read_resource(session, 'sajha-federation://up/file%3A%2F%2Fa')
    assert not can_read_resource(session, DATA)
    two = {'authenticated': True, 'prompt_rules': [['bug_*'], ['*_diagnosis']]}   # every layer
    assert can_see_prompt(two, PROMPT) and not can_see_prompt(two, 'bug_report')
    assert can_see_prompt({'authenticated': True}, 'anything')   # no rules: as before


class _Federation:
    def prompt_definitions(self):
        return [{'name': 'up__allowed', 'description': ''}, {'name': 'up__secret', 'description': ''}]

    def has_prompt(self, name):
        return name.startswith('up__')

    def get_prompt(self, name, arguments):
        return {'messages': [{'role': 'user', 'content': {'type': 'text', 'text': name}}]}

    def resource_definitions(self):
        return [{'uri': 'sajha-federation://up/a', 'name': 'a'}, {'uri': 'sajha-federation://up/b', 'name': 'b'}]

    def owns_resource(self, uri):
        return uri.startswith('sajha-federation://')

    def read_resource(self, uri):
        return {'contents': [{'uri': uri, 'text': 'x'}]}


def test_federated_prompts_and_resources_follow_the_rules(monkeypatch):
    from sajha.auth.access import SessionToolAccess
    from sajha.core.mcp_handler import MCPHandler
    from sajha.core.mcp_2025_11_25 import MCPError
    h = MCPHandler(auth_manager=SessionToolAccess())
    monkeypatch.setattr(MCPHandler, '_federation', staticmethod(lambda: _Federation()))
    monkeypatch.setattr(MCPHandler, '_fixtures', staticmethod(lambda: None))
    session = {'user_id': 'k', 'authenticated': True, 'tools': [], 'visible_tools': [],
               'prompt_rules': [['up__allowed']], 'resource_rules': [['sajha-federation://up/a']]}
    assert [p['name'] for p in h.handle_prompts_list({}, session=session)['prompts']] == ['up__allowed']
    with pytest.raises(MCPError):
        h.handle_prompts_get({'name': 'up__secret'}, session=session)
    assert h.handle_prompts_get({'name': 'up__allowed'}, session=session)['messages']
    uris = {r['uri'] for r in h._handle_resources_list({}, session=session)['resources']}
    assert 'sajha-federation://up/a' in uris and 'sajha-federation://up/b' not in uris
    with pytest.raises(MCPError) as e:
        h._handle_resources_read({'uri': 'sajha-federation://up/b'}, session=session)
    assert e.value.code == -32002
    assert h._handle_resources_read({'uri': 'sajha-federation://up/a'}, session=session)['contents']
    signed_in = {'user_id': 'u', 'authenticated': True, 'tools': ['*'], 'visible_tools': ['*']}
    assert len(h.handle_prompts_list({}, session=signed_in)['prompts']) == 2


# ── end to end ──────────────────────────────────────────────────────

def _db():
    from sajha.db.engine import get_db_session
    return get_db_session()


@pytest.fixture(scope='module')
def app():
    os.environ.pop('SAJHA_MCP_CONFORMANCE_FIXTURES', None)
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        yield c


def _key(mode, tool_list, owner=None):
    from sajha.auth import apikeys as svc
    from sajha.db.dao import UserDAO
    db = _db()
    try:
        user = UserDAO(db).get_by_user_id(owner) if owner else None
        _, raw = svc.create_key(db, name='x3-' + uuid.uuid4().hex[:6], created_by='test', owner=user,
                                mode=mode, tool_list=tool_list)
        return {'X-API-Key': raw}
    finally:
        db.close()


@pytest.fixture(scope='module')
def limited_user(app):
    """A user whose only role grants every tool, prompts bug_* and one data file."""
    from sajha.auth.password import hash_password
    from sajha.db.dao import UserDAO
    from sajha.db.models import Permission, Role, User
    tag = uuid.uuid4().hex[:8]
    db = _db()
    try:
        role = Role(name=f'x3_role_{tag}', description='X3 test')
        role.permissions.append(Permission(resource_type='tool', resource_name='*', actions='read,execute'))
        role.permissions.append(Permission(resource_type='prompt', resource_name='bug_*', actions='read'))
        role.permissions.append(Permission(resource_type='resource', resource_name=DATA, actions='read'))
        db.add(role)
        db.commit()
        user = User(user_id=f'x3_{tag}', user_name=f'x3_{tag}', email='', enabled=True,
                    password_hash=hash_password(PASSWORD))
        user.roles.append(role)
        UserDAO(db).create(user)
        uid, rid = user.user_id, role.id
    finally:
        db.close()
    from sajha.security import _login_throttle
    _login_throttle.reset()
    r = app.post('/api/auth/login', json={'user_id': uid, 'password': PASSWORD})
    assert r.status_code == 200, r.text
    yield uid, {'Authorization': f"Bearer {r.json()['token']}"}
    db = _db()
    try:
        user = UserDAO(db).get_by_user_id(uid)
        if user:
            UserDAO(db).delete(user)
        role = db.get(Role, rid)
        if role:
            db.delete(role)
            db.commit()
    finally:
        db.close()


def legacy(c, method, params, headers):
    return c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params},
                  headers=headers).json()


def modern(c, method, params, headers):
    params = dict(params, _meta=dict(META))
    hdrs = {'MCP-Protocol-Version': '2026-07-28', 'Mcp-Method': method,
            'Accept': 'application/json, text/event-stream', **headers}
    if method == 'prompts/get':
        hdrs['Mcp-Name'] = params['name']
    if method == 'resources/read':
        hdrs['Mcp-Name'] = params['uri']
    return c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params},
                  headers=hdrs).json()


def _reach(c, rpc, headers):
    """(prompt names listed, data URIs listed, may get PROMPT, may read DATA, may read OTHER_DATA)."""
    prompts = {p['name'] for p in rpc(c, 'prompts/list', {}, headers)['result']['prompts']}
    data = {r['uri'] for r in rpc(c, 'resources/list', {}, headers)['result']['resources']
            if r['uri'].startswith('sajha://data/')}
    got = 'result' in rpc(c, 'prompts/get', {'name': PROMPT, 'arguments': ARGS}, headers)
    read = 'result' in rpc(c, 'resources/read', {'uri': DATA}, headers)
    other = 'result' in rpc(c, 'resources/read', {'uri': OTHER_DATA}, headers)
    return prompts, data, got, read, other


@pytest.mark.parametrize('rpc', [legacy, modern])
@pytest.mark.parametrize('owner', [None, 'admin'])
def test_allowlisted_key_reaches_no_prompt_or_data_it_was_not_granted(app, rpc, owner):
    prompts, data, got, read, other = _reach(app, rpc, _key('allowlist', ['calc_*'], owner))
    assert prompts == set() and data == set() and not got and not read and not other


@pytest.mark.parametrize('rpc', [legacy, modern])
def test_granted_entries_open_exactly_those(app, rpc):
    headers = _key('allowlist', ['calc_*', 'prompt:bug_*', 'resource:' + DATA])
    prompts, data, got, read, other = _reach(app, rpc, headers)
    assert prompts and all(n.startswith('bug_') for n in prompts) and PROMPT in prompts
    assert data == {DATA} and got and read and not other


@pytest.mark.parametrize('rpc', [legacy, modern])
def test_all_and_denylist_keys_are_not_limited(app, rpc):
    for headers in (_key('all', []), _key('denylist', ['wiki_*'])):
        prompts, data, got, read, other = _reach(app, rpc, headers)
        assert PROMPT in prompts and {DATA, OTHER_DATA} <= data and got and read and other


@pytest.mark.parametrize('rpc', [legacy, modern])
def test_role_prompt_and_resource_permissions(app, rpc, limited_user):
    _, headers = limited_user
    prompts, data, got, read, other = _reach(app, rpc, headers)
    assert PROMPT in prompts and all(n.startswith('bug_') for n in prompts)
    assert data == {DATA} and got and read and not other


def test_owned_key_is_capped_by_role_and_entries(app, limited_user):
    uid, _ = limited_user
    headers = _key('all', ['prompt:*', 'resource:sajha://data/*'], owner=uid)   # the role still limits
    prompts, data, got, read, other = _reach(app, legacy, headers)
    assert all(n.startswith('bug_') for n in prompts) and data == {DATA} and not other


def test_rest_endpoints(app):
    headers = _key('allowlist', ['calc_*'])
    assert app.get('/api/prompts/list', headers=headers).json()['prompts'] == []
    assert app.get(f'/api/prompts/{PROMPT}', headers=headers).status_code == 404
    assert app.post(f'/api/prompts/{PROMPT}/render', json={'arguments': ARGS}, headers=headers).status_code == 404
    listed = app.post('/api/resources/list', json={}, headers=headers).json()['result']['resources']
    assert not any(r['uri'].startswith('sajha://data/') for r in listed)
    body = app.post('/api/resources/read', json={'params': {'uri': DATA}}, headers=headers).json()
    assert body['error']['code'] == -32002
    granted = _key('allowlist', ['calc_*', 'prompt:' + PROMPT, 'resource:' + DATA])
    assert [p['name'] for p in app.get('/api/prompts/list', headers=granted).json()['prompts']] == [PROMPT]
    assert app.get(f'/api/prompts/{PROMPT}', headers=granted).status_code == 200
    assert 'result' in app.post('/api/resources/read', json={'params': {'uri': DATA}}, headers=granted).json()


def test_console_pages(app, limited_user):
    _, headers = limited_user
    page = app.get('/prompts', headers=headers)
    assert page.status_code == 200 and PROMPT in page.text and 'code_review' not in page.text
    assert app.get(f'/prompts/{PROMPT}', headers=headers).status_code == 200
    from sajha.app import prompts_registry
    other = next(n for n in prompts_registry.prompts if not n.startswith('bug_'))
    assert app.get(f'/prompts/{other}', headers=headers).status_code == 404
    assert app.get(f'/prompts/{other}/test', headers=headers).status_code == 404


def test_key_form_fields_become_entries():
    from sajha.routes.apikeys_routes import _tool_list
    assert _tool_list({'tool_list': ['calc_*'], 'prompt_list': 'bug_*\ncode_*',
                       'resource_list': ['sajha://data/*.csv']}) == [
        'calc_*', 'prompt:bug_*', 'prompt:code_*', 'resource:sajha://data/*.csv']
