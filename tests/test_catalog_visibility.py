"""
Catalog visibility beyond tools/list: prompts (MCP and REST), the catalog resources,
completion/complete and the A2A agent card follow the same policy as the tool catalog
(sajha/auth/access.py). Anonymous callers see only what ``mcp.anonymous.*`` allows.

Also: FRED tools fetch newest first; plugin min_sajha_version compares as a version.
"""

import json
import os
import sys
import urllib.parse
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

PROMPT = 'bug_diagnosis'
ENUM_TOOL, ENUM_ARG = 'boc_get_bond_yield', 'bond_term'
META = {'io.modelcontextprotocol/protocolVersion': '2026-07-28',
        'io.modelcontextprotocol/clientCapabilities': {},
        'io.modelcontextprotocol/clientInfo': {'name': 'pytest', 'version': '1'}}


@pytest.fixture(scope='module')
def client():
    os.environ.pop('SAJHA_MCP_CONFORMANCE_FIXTURES', None)
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope='module')
def admin(client):
    from sajha.security import _login_throttle
    _login_throttle.reset()
    r = client.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'})
    assert r.status_code == 200, r.text
    return {'Authorization': f"Bearer {r.json()['token']}"}


def legacy(client, method, params=None, headers=None):
    r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}},
                    headers=headers or {})
    return r.json()


def modern(client, method, params=None, headers=None):
    params = dict(params or {}, _meta=dict(META))
    hdrs = {'MCP-Protocol-Version': '2026-07-28', 'Mcp-Method': method,
            'Accept': 'application/json, text/event-stream'}
    if method in ('prompts/get',):
        hdrs['Mcp-Name'] = params['name']
    if method == 'resources/read':
        hdrs['Mcp-Name'] = params['uri']
    hdrs.update(headers or {})
    return client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params},
                       headers=hdrs).json()


def _prompt_names(body):
    assert 'result' in body, body
    return {p['name'] for p in body['result']['prompts']}


def _catalog(body):
    assert 'result' in body, body
    return {t['name'] for t in json.loads(body['result']['contents'][0]['text'])}


# ── prompts ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('rpc', [legacy, modern])
def test_prompts_list_follows_the_anonymous_policy(client, admin, rpc, monkeypatch):
    assert PROMPT not in _prompt_names(rpc(client, 'prompts/list'))
    assert PROMPT in _prompt_names(rpc(client, 'prompts/list', headers=admin))
    monkeypatch.setenv('SAJHA_MCP_ANONYMOUS_PROMPTS', 'bug_*')
    assert _prompt_names(rpc(client, 'prompts/list')) == {PROMPT}


@pytest.mark.parametrize('rpc', [legacy, modern])
def test_prompts_get_hidden_prompt_is_unknown(client, admin, rpc, monkeypatch):
    args = {'name': PROMPT, 'arguments': {'bug_description': 'x', 'error_message': 'e',
                                          'code': 'c', 'language': 'py'}}
    r = rpc(client, 'prompts/get', args)
    assert r['error']['code'] == -32602 and 'Unknown prompt' in r['error']['message']
    assert 'messages' in rpc(client, 'prompts/get', args, headers=admin)['result']
    monkeypatch.setenv('SAJHA_MCP_ANONYMOUS_PROMPTS', PROMPT)
    assert 'messages' in rpc(client, 'prompts/get', args)['result']


def test_prompts_list_cache_scope(client, admin):
    assert modern(client, 'prompts/list')['result']['cacheScope'] == 'public'
    assert modern(client, 'prompts/list', headers=admin)['result']['cacheScope'] == 'private'


def test_rest_prompt_endpoints(client, admin, monkeypatch):
    names = {p['name'] for p in client.get('/api/prompts/list').json()['prompts']}
    assert PROMPT not in names
    assert client.get(f'/api/prompts/{PROMPT}').status_code == 404
    names = {p['name'] for p in client.get('/api/prompts/list', headers=admin).json()['prompts']}
    assert PROMPT in names
    assert client.get(f'/api/prompts/{PROMPT}', headers=admin).status_code == 200
    monkeypatch.setenv('SAJHA_MCP_ANONYMOUS_PROMPTS', PROMPT)
    assert client.get(f'/api/prompts/{PROMPT}').status_code == 200
    monkeypatch.setenv('SAJHA_MCP_ANONYMOUS_ENABLED', 'false')
    assert client.get('/api/prompts/list').status_code == 401
    assert client.get('/api/prompts/list', headers={'X-API-Key': 'sja_not_a_real_key'}).status_code == 401


# ── catalog resources ────────────────────────────────────────────────

@pytest.mark.parametrize('rpc', [legacy, modern])
def test_tool_catalog_resource_follows_tools_list(client, admin, rpc, monkeypatch):
    read = {'uri': 'sajha://tools/catalog'}
    assert _catalog(rpc(client, 'resources/read', read)) == set()
    assert len(_catalog(rpc(client, 'resources/read', read, headers=admin))) > 10
    monkeypatch.setenv('SAJHA_MCP_ANONYMOUS_TOOLS', 'calc_*')
    names = _catalog(rpc(client, 'resources/read', read))
    assert names and all(n.startswith('calc_') for n in names)


@pytest.mark.parametrize('rpc', [legacy, modern])
def test_prompt_catalog_resource_and_counts(client, admin, rpc):
    anon = rpc(client, 'resources/list')['result']['resources']
    tool_cat = next(r for r in anon if r['uri'] == 'sajha://tools/catalog')
    assert tool_cat['description'] == 'Catalog of 0 available MCP tools'
    assert not any(r['uri'] == 'sajha://prompts/catalog' for r in anon)   # nothing to show
    body = rpc(client, 'resources/read', {'uri': 'sajha://prompts/catalog'})
    assert _catalog(body) == set()
    assert PROMPT in _catalog(rpc(client, 'resources/read', {'uri': 'sajha://prompts/catalog'}, headers=admin))


DATA_URI = 'sajha://data/customers.csv'
NOT_FOUND = (-32002, -32602)     # 2025-11-25: -32002; 2026-07-28: invalid params


def _data_uris(body):
    assert 'result' in body, body
    return {r['uri'] for r in body['result']['resources'] if r['uri'].startswith('sajha://data/')}


@pytest.mark.parametrize('rpc', [legacy, modern])
def test_data_resources_follow_the_anonymous_policy(client, admin, rpc, monkeypatch):
    monkeypatch.delenv('SAJHA_MCP_ANONYMOUS_RESOURCES', raising=False)
    assert _data_uris(rpc(client, 'resources/list')) == set()
    r = rpc(client, 'resources/read', {'uri': DATA_URI})
    assert r['error']['code'] in NOT_FOUND and 'customer_id' not in json.dumps(r)
    assert DATA_URI in _data_uris(rpc(client, 'resources/list', headers=admin))
    r = rpc(client, 'resources/read', {'uri': DATA_URI}, headers=admin)
    assert 'customer_id' in r['result']['contents'][0]['text']

    monkeypatch.setenv('SAJHA_MCP_ANONYMOUS_RESOURCES', DATA_URI)
    assert _data_uris(rpc(client, 'resources/list')) == {DATA_URI}
    assert 'customer_id' in rpc(client, 'resources/read', {'uri': DATA_URI})['result']['contents'][0]['text']
    r = rpc(client, 'resources/read', {'uri': 'sajha://data/orders.csv'})
    assert r['error']['code'] in NOT_FOUND
    monkeypatch.setenv('SAJHA_MCP_ANONYMOUS_RESOURCES', 'sajha://data/*')
    for uri in ('sajha://data/../../config/users.json', 'sajha://data/..', 'sajha://data/'):
        r = rpc(client, 'resources/read', {'uri': uri})
        assert r['error']['code'] in NOT_FOUND and 'admin123' not in json.dumps(r), uri
    monkeypatch.setenv('SAJHA_MCP_ANONYMOUS_ENABLED', 'false')
    assert 'customer_id' not in json.dumps(rpc(client, 'resources/read', {'uri': DATA_URI}))


def test_rest_data_resources(client, admin):
    assert client.post('/api/resources/list', json={}).status_code == 401
    assert client.post('/api/resources/read', json={'params': {'uri': DATA_URI}}).status_code == 401
    listed = {r['uri'] for r in client.post('/api/resources/list', json={}, headers=admin)
              .json()['result']['resources']}
    assert DATA_URI in listed
    r = client.post('/api/resources/read', json={'params': {'uri': DATA_URI}}, headers=admin).json()
    assert 'customer_id' in r['result']['contents'][0]['text']
    r = client.post('/api/resources/read', headers=admin,
                    json={'params': {'uri': 'sajha://data/../../config/users.json'}}).json()
    assert r['error']['code'] == -32002 and 'admin123' not in json.dumps(r)


def test_rest_resource_mirrors_filter_by_policy(client, admin):
    from sajha.db.engine import get_db_session
    from sajha.db.dao import ApiKeyDAO
    from sajha.db.models import ApiKey
    import uuid
    raw = f'sja_{uuid.uuid4().hex}{uuid.uuid4().hex}'
    db = get_db_session()
    try:
        dao = ApiKeyDAO(db)
        dao.create(ApiKey(key_hash=dao.hash_key(raw), key_prefix=raw[:8], name=f'vis-{raw[-6:]}',
                          tool_access_mode='allowlist', tool_access_list=json.dumps(['calc_*'])))
    finally:
        db.close()
    key = {'X-API-Key': raw}
    r = client.post('/api/resources/read', json={'params': {'uri': 'sajha://tools/catalog'}}, headers=key)
    names = {t['name'] for t in json.loads(r.json()['result']['contents'][0]['text'])}
    assert names and all(n.startswith('calc_') for n in names)
    r = client.post('/api/completion/complete', headers=key, json={'params': {
        'ref': {'type': 'ref/tool', 'name': ENUM_TOOL}, 'argument': {'name': ENUM_ARG, 'value': ''}}})
    assert r.json()['result']['completion']['values'] == []
    r = client.post('/api/completion/complete', headers=admin, json={'params': {
        'ref': {'type': 'ref/tool', 'name': ENUM_TOOL}, 'argument': {'name': ENUM_ARG, 'value': ''}}})
    assert r.json()['result']['completion']['values']


# ── completion ──────────────────────────────────────────────────────

@pytest.mark.parametrize('rpc', [legacy, modern])
def test_completion_only_for_visible_tools(client, admin, rpc):
    params = {'ref': {'type': 'ref/tool', 'name': ENUM_TOOL}, 'argument': {'name': ENUM_ARG, 'value': ''}}
    assert rpc(client, 'completion/complete', params)['result']['completion']['values'] == []
    assert rpc(client, 'completion/complete', params, headers=admin)['result']['completion']['values'] == \
        ['2y', '5y', '10y', '30y']


# ── agent card ───────────────────────────────────────────────────────

def test_agent_card_is_generic_for_anonymous(client, admin, monkeypatch):
    card = client.get('/.well-known/agent.json').json()
    assert card['skills'] == [] and card['name'] and card['capabilities']
    assert client.get('/.well-known/agent.json', headers=admin).json()['skills']
    monkeypatch.setenv('SAJHA_MCP_ANONYMOUS_TOOLS', 'calc_*')
    skills = client.get('/.well-known/agent.json').json()['skills']
    assert skills and all(s['id'].startswith('calc_') for s in skills)


# ── FRED: newest first ───────────────────────────────────────────────

def _fred_classes():
    from sajha.tools.impl import fred_tools
    return [c for n, c in vars(fred_tools).items()
            if isinstance(c, type) and issubclass(c, fred_tools.FREDBaseTool) and c is not fred_tools.FREDBaseTool]


@pytest.mark.parametrize('cls', _fred_classes(), ids=lambda c: c.__name__)
def test_every_fred_tool_asks_for_the_latest_observations(cls):
    from sajha.tools.impl import fred_tools
    seen = []

    def fake_get(self, endpoint, **params):
        seen.append((endpoint, params))
        return {'observations': []}

    tool = cls({'name': 'fred_x', 'api_key': 'k'})
    with mock.patch.object(fred_tools.FREDBaseTool, '_fred_get', fake_get):
        tool.execute({'series_id': 'UNRATE', 'limit': 5})
    endpoint, params = seen[0]
    assert endpoint == 'series/observations'
    assert params['sort_order'] == 'desc' and params['limit'] == 5


def test_fred_request_carries_sort_order():
    from sajha.tools.impl import fred_tools
    urls = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, *a, **k):
        urls.append(req.full_url)
        return _Resp()

    tool = fred_tools.FREDGDPTool({'name': 'fred_gdp', 'api_key': 'k'})
    with mock.patch.object(fred_tools.urllib.request, 'urlopen', fake_urlopen), \
            mock.patch.object(fred_tools, 'safe_json_response', lambda *a, **k: {'observations': []}):
        tool.execute({'limit': 3})
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(urls[0]).query))
    assert (q['series_id'], q['sort_order'], q['limit']) == ('GDP', 'desc', '3')


# ── plugins: versions compare as versions ─────────────────────────────

@pytest.mark.parametrize('older,newer', [
    ('4.9.2', '4.10.0'), ('5.0.0', '10.0.0'), ('5.0.0rc1', '5.0.0'), ('5.2', '5.10'), ('v5.1.0', '5.1.1'),
])
def test_version_less_than(older, newer):
    from sajha.core.plugins import version_less_than
    assert version_less_than(older, newer)
    assert not version_less_than(newer, older)


def test_version_less_than_equal_versions():
    from sajha.core.plugins import version_less_than
    assert not version_less_than('5.0', '5.0.0') and not version_less_than('5.0.0', '5.0')


def test_plugin_validate_compares_versions_numerically(tmp_path, monkeypatch):
    from sajha.core import plugins
    import sajha.app
    monkeypatch.setattr(sajha.app, 'VERSION', '5.10.0')
    (tmp_path / 'tools').mkdir()
    mgr = plugins.PluginManager.__new__(plugins.PluginManager)
    manifest = plugins.PluginManifest(name='p', version='1.0.0', path=str(tmp_path),
                                      min_sajha_version='5.9.0')
    ok, errors = mgr.validate(manifest)
    assert not any('Requires SAJHA' in e for e in errors), errors     # "5.9.0" > "5.10.0" as strings
    manifest.min_sajha_version = '5.11.0'
    ok, errors = mgr.validate(manifest)
    assert any('Requires SAJHA >= 5.11.0' in e for e in errors)


@pytest.mark.parametrize('method', ['tool/schema', 'tool/description', 'tool/input_schema',
                                    'tool/output_schema'])
def test_tool_schema_extension_methods_follow_the_policy(client, admin, method):
    r = legacy(client, method, {'name': ENUM_TOOL})
    assert 'error' in r and 'Tool not found' in r['error']['message']
    assert 'result' in legacy(client, method, {'name': ENUM_TOOL}, headers=admin)
