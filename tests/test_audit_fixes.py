# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Regressions for defects found by the documentation audit: OLAP operation binding,
REST catalog visibility, JSON Schema argument validation, the Yahoo symbol pattern, FRED
"latest" ordering, per-upstream federation rate limits, plugin .py tools, the SharePoint
tools (Graph, token expiry, schemas, escaping, config keys), ${key:default} resolution,
the landing page counts, dead-code cleanups, and change-event coalescing.
All HTTP is mocked."""
import base64
import json
import os
import urllib.parse
from pathlib import Path
from unittest import mock

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


def _config(name: str) -> dict:
    return json.loads((ROOT / 'config' / 'tools' / f'{name}.json').read_text())


# ── 1. OLAP: the operation is the tool's own name ───────────────────────────

def test_olap_tool_refuses_a_caller_chosen_operation():
    from sajha.tools.impl.duckdb_olap_advanced import DuckDBOLAPAdvancedTool
    tool = DuckDBOLAPAdvancedTool(_config('olap_pivot_table'))
    with mock.patch.object(tool, 'call_tool') as call:
        with pytest.raises(ValueError, match='_tool_name'):
            tool.execute({'_tool_name': 'olap_generate_sample_data', 'dataset': 'x'})
        call.assert_not_called()

    async def fake(name, args):
        return {'ran': name}
    with mock.patch.object(tool, 'call_tool', side_effect=fake) as call:
        assert tool.execute({'dataset': 'sales'}) == {'ran': 'olap_pivot_table'}
        assert call.call_args[0][0] == 'olap_pivot_table'


# ── 3. JSON Schema argument validation in execute_with_tracking ────────────

def _schema_tool(schema):
    from sajha.tools.base_mcp_tool import BaseMCPTool

    class T(BaseMCPTool):
        ran = []

        def execute(self, arguments):
            self.ran.append(arguments)
            return {'ok': True}

        def get_input_schema(self):
            return schema

        def get_output_schema(self):
            return {}

    return T({'name': 'zz_schema_probe', 'inputSchema': schema})


SCHEMA = {
    'type': 'object',
    'properties': {
        'symbol': {'type': 'string', 'pattern': '^[A-Z]{1,5}$'},
        'period': {'type': 'string', 'enum': ['1d', '1mo']},
        'count': {'type': 'integer', 'minimum': 1, 'maximum': 10},
    },
    'required': ['symbol'],
    'additionalProperties': False,
}


@pytest.mark.parametrize('args, fragment', [
    ({}, 'Missing required parameter: symbol'),
    ({'symbol': 'toolong'}, "'symbol'"),
    ({'symbol': 'AAPL', 'period': '5y'}, "'period'"),
    ({'symbol': 'AAPL', 'count': 0}, "'count'"),
    ({'symbol': 'AAPL', 'count': 'three'}, "'count'"),
    ({'symbol': 'AAPL', 'extra': 1}, 'extra'),
])
def test_arguments_are_validated_against_the_schema(args, fragment):
    from sajha.tools.base_mcp_tool import ToolArgumentError
    tool = _schema_tool(SCHEMA)
    with pytest.raises(ToolArgumentError) as e:
        tool.execute_with_tracking(args)
    assert fragment in str(e.value) and 'zz_schema_probe' in str(e.value)
    assert tool.ran == []                       # the tool never ran


def test_valid_arguments_pass_and_a_broken_schema_falls_back_to_required():
    from sajha.tools.base_mcp_tool import ToolArgumentError
    assert _schema_tool(SCHEMA).execute_with_tracking({'symbol': 'AAPL', 'count': 3}) == {'ok': True}
    broken = {'type': 'object', 'properties': {'q': {'type': 'string', 'required': True}}, 'required': ['q']}
    tool = _schema_tool(broken)
    assert tool.execute_with_tracking({'q': 1}) == {'ok': True}       # types not enforced
    with pytest.raises(ToolArgumentError, match='q'):
        tool.execute_with_tracking({})


def test_every_builtin_tool_schema_is_valid_json_schema():
    import jsonschema
    bad = []
    for path in sorted((ROOT / 'config' / 'tools').glob('*.json')):
        schema = json.loads(path.read_text()).get('inputSchema')
        if not schema:
            continue
        try:
            jsonschema.Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as e:
            bad.append(f'{path.name}: {e.message}')
    assert bad == []


def test_validation_error_per_era():
    """2026-07-28: -32602; 2025-11-25: a CallToolResult with isError (SEP-1303)."""
    from sajha.core.mcp_2025_11_25 import MCPError
    from sajha.core.mcp_handler import MCPHandler
    tool = _schema_tool(SCHEMA)
    class Reg:
        tools = {'zz_schema_probe': tool}

        def get_tool(self, name):
            return self.tools.get(name)

        def get_all_tools(self):
            return [tool.to_mcp_format()]

    handler = MCPHandler(tools_registry=Reg())
    params = {'name': 'zz_schema_probe', 'arguments': {'symbol': 'lower'}}
    legacy = handler._handle_tools_call(params, None, 'legacy')
    assert legacy['isError'] is True and "'symbol'" in legacy['content'][0]['text']
    with pytest.raises(MCPError) as e:
        handler._handle_tools_call(params, None, 'modern')
    assert e.value.code == -32602


def test_rest_execute_answers_400_for_invalid_arguments(web):
    c, admin = web
    r = c.post('/api/tools/execute', cookies=admin,
               json={'tool': 'calc_percentage_change', 'arguments': {'old_value': 'eighty', 'new_value': 100}})
    assert r.status_code == 400 and 'old_value' in r.json()['error']
    r = c.post('/api/tools/execute', cookies=admin,
               json={'tool': 'calc_percentage_change', 'arguments': {'old_value': 80, 'new_value': 100}})
    assert r.status_code == 200 and r.json()['success']


# ── 4. Yahoo symbols ────────────────────────────────────────────────────────

@pytest.mark.parametrize('symbol', ['AAPL', 'BRK-A', 'BTC-USD', '7203.T', '^GSPC', 'EURUSD=X', 'ES=F', 'aapl'])
def test_yahoo_symbol_pattern_accepts_real_symbols(symbol):
    import jsonschema
    from sajha.tools.impl.yahoo_finance_tool import YahooGetQuoteTool
    for schema in (YahooGetQuoteTool().get_input_schema(), _config('yahoo_get_quote')['inputSchema'],
                   _config('yahoo_get_history')['inputSchema']):
        jsonschema.validate({'symbol': symbol, **({'period': '1mo'} if 'period' in schema.get('required', []) else {})},
                            {**schema, 'required': ['symbol']})


@pytest.mark.parametrize('symbol', ['AAPL/../x', 'A B', '', 'X' * 21])
def test_yahoo_symbol_pattern_still_rejects_junk(symbol):
    import jsonschema
    schema = _config('yahoo_get_quote')['inputSchema']['properties']['symbol']
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(symbol, schema)


# ── 5. FRED: the latest observation is the newest ──────────────────────────

class _FredResp:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fred_latest_asks_newest_first_and_skips_missing_values():
    from sajha.tools.impl import fed_reserve_tool_refactored as mod
    seen = []

    def fake_urlopen(url, *a, **k):
        seen.append(url)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        if '/series/observations' in url:
            return _FredResp({'observations': [{'date': '2026-09-01', 'value': '.'},
                                               {'date': '2026-08-01', 'value': '4.2'},
                                               {'date': '2026-07-01', 'value': '4.1'}]})
        return _FredResp({'seriess': [{'title': 'Unemployment Rate', 'units': '%', 'frequency': 'Monthly'}]})

    def fake_json(resp, *a, **k):
        return json.loads(resp.payload)

    tool = mod.FedGetLatestTool({'api_key': 'k'})
    tool.api_key = 'k'
    with mock.patch.object(mod.urllib.request, 'urlopen', fake_urlopen), \
            mock.patch.object(mod, 'safe_json_response', fake_json):
        out = tool.execute({'series_id': 'UNRATE'})
        assert (out['date'], out['value']) == ('2026-08-01', 4.2)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(seen[0]).query))
        assert q['sort_order'] == 'desc'
        common = mod.FedGetCommonIndicatorsTool({'api_key': 'k'})
        common.api_key = 'k'
        res = common.execute({'indicators': ['unemployment']})
        assert res['indicators']['unemployment']['date'] == '2026-08-01'


# ── 6. Federation: one rate-limit window per upstream ──────────────────────

def test_federation_rate_limit_is_per_upstream():
    from sajha.federation.config import UpstreamConfig
    from sajha.federation.manager import _Upstream
    a = _Upstream(UpstreamConfig(id='alpha', url='http://a', max_calls_per_minute=2))
    b = _Upstream(UpstreamConfig(id='beta', url='http://b', max_calls_per_minute=2))
    assert a.limiter.name != b.limiter.name
    a.limiter.reset(), b.limiter.reset()
    assert a.limiter.is_allowed('calls') and a.limiter.is_allowed('calls')
    assert not a.limiter.is_allowed('calls')
    assert b.limiter.is_allowed('calls')          # alpha's window does not throttle beta
    a.limiter.reset(), b.limiter.reset()


# ── 7. Plugins: loose .py tools register ────────────────────────────────────

def test_plugin_python_tools_register(tmp_path, monkeypatch):
    from sajha.core.plugins import PluginManager
    plugin = tmp_path / 'demo'
    (plugin / 'tools').mkdir(parents=True)
    (plugin / 'plugin.json').write_text(json.dumps({'name': 'demo', 'version': '1.0.0',
                                                    'min_sajha_version': '0.0.0'}))
    (plugin / 'tools' / 'echo_tool.py').write_text('''
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.base_mcp_tool import ToolArgumentError   # imported, not a tool: ignored

class EchoTool(BaseMCPTool):
    def execute(self, arguments):
        return {"echo": arguments.get("text")}
    def get_input_schema(self):
        return {"type": "object", "properties": {"text": {"type": "string"}}}
    def get_output_schema(self):
        return {}

class NamedTool(EchoTool):
    def __init__(self, config=None):
        super().__init__({"name": "zz_named_plugin_tool"})
''')

    class Reg:
        def __init__(self):
            self.tools = {}

        def register_tool(self, tool):          # one argument, like ToolsRegistry.register_tool
            self.tools[tool.name] = tool

        def unregister_tool(self, name):
            self.tools.pop(name, None)

    reg = Reg()
    pm = PluginManager(reg)
    pm.PLUGINS_DIR = str(tmp_path)
    pm.discover()
    status = pm.load_plugin('demo')
    assert status.error == '' and status.tools_registered == 2
    assert set(reg.tools) == {'echotool', 'zz_named_plugin_tool'}
    assert reg.tools['echotool'].execute({'text': 'hi'}) == {'echo': 'hi'}
    pm.unload_plugin('demo')
    assert reg.tools == {}


# ── 8. SharePoint: Microsoft Graph, token expiry, schemas, escaping, config ─

class _Http:
    """Stands in for requests.post (token) and requests.request (Graph)."""

    def __init__(self, routes):
        self.routes, self.calls, self.tokens = routes, [], 0

    def post(self, url, data=None, timeout=None):
        self.tokens += 1
        assert url == 'https://login.microsoftonline.com/tenant-1/oauth2/v2.0/token'
        assert data['scope'] == 'https://graph.microsoft.com/.default'
        return _Resp({'access_token': f'tok{self.tokens}', 'expires_in': 3599})

    def request(self, method, url, params=None, json=None, data=None, headers=None, timeout=None):
        self.calls.append((method, url, params, json, headers))
        assert headers['Authorization'].startswith('Bearer tok')
        assert url.startswith('https://graph.microsoft.com/v1.0/')
        for (m, prefix), payload in self.routes.items():
            if m == method and url.startswith(prefix):
                return _Resp(payload(url) if callable(payload) else payload)
        raise AssertionError(f'unexpected {method} {url}')


class _Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status
        self.content = b'x' if payload is not None else b''
        self.headers = {'Content-Type': 'application/json'}
        self.text = ''

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


SITE = 'https://graph.microsoft.com/v1.0/sites/'


def _sp(cls, name, **extra):
    cfg = _config(name)
    cfg.update(site_url='https://contoso.sharepoint.com/sites/team',
               authentication={'type': 'client_credentials', 'tenant_id': 'tenant-1',
                               'client_id': 'cid', 'client_secret': 'secret'}, **extra)
    return cls(cfg)


def test_sharepoint_unconfigured_answers_without_http():
    from sajha.tools.impl import sharepoint_tool as sp
    tool = sp.SharePointDocumentTool(_config('sharepoint_documents'))     # raw ${...} placeholders
    with mock.patch.object(sp.requests, 'request') as req, mock.patch.object(sp.requests, 'post') as post:
        out = tool.execute({'operation': 'list_files'})
    assert out['success'] is False and 'not configured' in out['error']
    req.assert_not_called(), post.assert_not_called()


def test_sharepoint_documents_use_graph_with_a_cached_token():
    from sajha.tools.impl import sharepoint_tool as sp
    http = _Http({
        ('GET', SITE + 'contoso.sharepoint.com:/sites/team'): {'id': 'site,1,2'},
        ('GET', SITE + 'site%2C1%2C2/drive/root:/Project:/children'):
            {'value': [{'name': 'plan.docx', 'id': 'i1', 'size': 10, 'file': {},
                        'parentReference': {'path': '/drive/root:/Project'}}]},
        ('GET', SITE + 'site%2C1%2C2/drive/root/search'): {'value': []},
    })
    tool = _sp(sp.SharePointDocumentTool, 'sharepoint_documents')
    with mock.patch.object(sp.requests, 'post', http.post), mock.patch.object(sp.requests, 'request', http.request):
        out = tool.execute({'operation': 'list_files', 'folder_path': '/sites/team/Shared Documents/Project'})
        assert out['success'], out
        assert out['files'][0]['name'] == 'plan.docx' and out['files'][0]['path'] == '/Project/plan.docx'
        out = tool.execute({'operation': 'search', 'query': "O'Brien report"})
        assert out['success'], out
    assert http.tokens == 1                              # expiry computed with timedelta: cached
    assert tool.authenticator.token_expiry > tool.authenticator.token_expiry.now()
    search_url = http.calls[-1][1]
    assert "search(q='O%27%27Brien%20report')" in search_url      # OData literal, then URL-encoded


def test_sharepoint_token_expiry_survives_long_lifetimes():
    from sajha.tools.impl import sharepoint_tool as sp
    auth = sp.SharePointAuthenticator({'tenant_id': 'tenant-1', 'client_id': 'c', 'client_secret': 's'})
    with mock.patch.object(sp.requests, 'post', return_value=_Resp({'access_token': 't', 'expires_in': 86399})):
        assert auth.get_access_token() == 't'           # replace(second=...) used to raise here


def test_sharepoint_lists_escape_names_and_send_filters_encoded():
    from sajha.tools.impl import sharepoint_tool as sp
    http = _Http({
        ('GET', SITE + 'contoso.sharepoint.com:/sites/team'): {'id': 'S'},
        ('GET', SITE + "S/lists/Bob%27s%20List/items"): {'value': [{'id': '1', 'fields': {'Title': 'a'}}]},
    })
    tool = _sp(sp.SharePointListTool, 'sharepoint_lists')
    with mock.patch.object(sp.requests, 'post', http.post), mock.patch.object(sp.requests, 'request', http.request):
        out = tool.execute({'operation': 'query_items', 'list_name': "Bob's List",
                            'filter': "fields/Status eq 'Active'"})
    assert out['success'], out
    _, url, params, _, headers = http.calls[-1]
    assert params['$filter'] == "fields/Status eq 'Active'"          # requests encodes params
    assert headers['Prefer'].startswith('HonorNonIndexedQueries')


def test_sharepoint_search_uses_graph_search_scoped_to_the_site():
    from sajha.tools.impl import sharepoint_tool as sp
    http = _Http({('POST', 'https://graph.microsoft.com/v1.0/search/query'): {'value': [{'hitsContainers': [
        {'total': 1, 'hits': [{'summary': 's', 'resource': {'name': 'budget.xlsx', 'webUrl': 'u'}}]}]}]}})
    tool = _sp(sp.SharePointSearchTool, 'sharepoint_search', search_region='NAM')
    with mock.patch.object(sp.requests, 'post', http.post), mock.patch.object(sp.requests, 'request', http.request):
        out = tool.execute({'query': 'budget', 'search_type': 'documents', 'file_types': ['xlsx']})
    assert out['success'] and out['results'][0]['title'] == 'budget.xlsx'
    req = http.calls[-1][3]['requests'][0]
    assert req['entityTypes'] == ['driveItem'] and req['region'] == 'NAM'
    assert 'filetype:xlsx' in req['query']['queryString']
    assert 'path:"https://contoso.sharepoint.com/sites/team"' in req['query']['queryString']


def test_sharepoint_schemas_and_config_keys():
    for name, required in (('sharepoint_documents', ['operation']), ('sharepoint_lists', ['operation']),
                           ('sharepoint_search', ['query'])):
        schema = _config(name)['inputSchema']
        assert schema['required'] == required
        assert not any('required' in p for p in schema['properties'].values())
    cfg = yaml.safe_load((ROOT / 'config' / 'application.yml').read_text())
    assert set(cfg['sharepoint']) == {'site', 'client'}
    assert cfg['sharepoint']['site']['url'] == '${SHAREPOINT_SITE_URL:}'
    assert cfg['azure']['tenant']['id'] == '${AZURE_TENANT_ID:}'
    assert 'oauth' not in cfg                                         # the dead section is gone


def test_studio_sharepoint_generator_writes_a_valid_schema():
    import jsonschema
    from sajha.studio.sharepoint_tool_generator import SharePointToolConfig, SharePointToolGenerator
    gen = SharePointToolGenerator.__new__(SharePointToolGenerator)
    for kind in ('documents', 'lists', 'sites', 'search'):
        schema = gen._build_input_schema(SharePointToolConfig(name='zz', description='d', tool_type=kind,
                                                              site_url='https://x.sharepoint.com'))
        jsonschema.Draft202012Validator.check_schema(schema)
        assert schema['required'] == (['query'] if kind == 'search' else ['operation'])


# ── 9. ${key:default} never becomes a directory name ───────────────────────

def test_properties_configurator_honours_inline_defaults():
    from sajha.core.properties_configurator import PropertiesConfigurator
    pc = PropertiesConfigurator()
    assert pc._resolve_value('${zz.not.defined:./data/x}/f', {}, set()) == './data/x/f'
    assert pc._resolve_value('${zz.defined:./other}', {'zz.defined': 'yes'}, set()) == 'yes'
    assert pc._resolve_value('${zz.not.defined}', {}, set()) == '${zz.not.defined}'


def test_raw_tool_configs_never_create_placeholder_directories(tmp_path, monkeypatch):
    from sajha.core.config import resolve_placeholders
    from sajha.tools.impl.duckdb_olap_tools_refactored import DuckDbListTablesTool
    from sajha.tools.impl.sqlselect_tool_refactored import SqlSelectListSourcesTool
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('data.duckdb.dir', raising=False)
    monkeypatch.setenv('SAJHA_DATA_DUCKDB_DIR', str(tmp_path / 'duck'))
    monkeypatch.setenv('SAJHA_DATA_SQLSELECT_DIR', str(tmp_path / 'sql'))
    assert resolve_placeholders('${data.duckdb.dir:./data/duckdb}') == str(tmp_path / 'duck')
    assert resolve_placeholders('${zz.unknown:fallback}') == 'fallback'
    DuckDbListTablesTool(_config('duckdb_list_tables'))          # raw: "${data.duckdb.dir:./data/duckdb}"
    SqlSelectListSourcesTool(_config('sqlselect_list_sources'))
    assert not [p for p in tmp_path.iterdir() if p.name.startswith('${')]
    assert (tmp_path / 'duck').is_dir()


def test_stray_placeholder_directories_are_gone():
    assert not [p.name for p in ROOT.iterdir() if p.name.startswith('${')]


def test_olap_datasets_resolve_the_data_directory():
    from sajha.olap.semantic_layer import SemanticLayer
    layer = SemanticLayer(str(ROOT / 'config' / 'olap'))
    ds = layer.datasets['customer_olap']
    assert '${' not in ds.source_table and all('${' not in j.table for j in ds.joins)


# ── 10. Landing page counts come from the server ───────────────────────────

def test_landing_counts_are_derived(web):
    c, _ = web
    from sajha.ai.llm.registry import registered_providers
    from sajha.db.models import Base
    html = c.get('/').text
    assert '6 LLM providers' not in html and '79+' not in html
    n = len([p for p in registered_providers() if p != 'mock'])
    assert f'{n} LLM provider types' in html
    assert f'<span class="lp2-num">{len(Base.metadata.tables)}</span><span class="lp2-label">Database Tables' in html


# ── 11. Cleanups ────────────────────────────────────────────────────────────

def test_dead_modules_and_routes_are_gone(web):
    c, _ = web
    assert not (ROOT / 'sajha' / 'core' / 'auth_manager.py').exists()
    assert not (ROOT / 'sajha' / 'core' / 'apikey_manager.py').exists()
    from sajha.routes import health_routes, ops_routes
    assert [r.path for r in health_routes.router.routes].count('/health') == 1
    assert '/health' not in [r.path for r in ops_routes.router.routes]
    assert c.get('/health').json()['status'] == 'healthy'
    from sajha.core.config import Settings
    assert not [f for f in Settings.model_fields if f.startswith('oauth_')]
    from sajha.core.mcp_2025_11_25 import SSEEventTracker
    assert not hasattr(SSEEventTracker, 'get_events_after')


def test_studio_menu_lists_the_sharepoint_creator(web):
    c, admin = web
    html = c.get('/dashboard', cookies=admin).text
    assert 'studio/sharepoint' in html and 'Documents, lists or search on a SharePoint site' in html


def test_enable_disable_does_not_write_resolved_secrets(tmp_path):
    """Toggling a tool persists only 'enabled'; the file keeps its ${...} references."""
    from sajha.tools.tools_registry import ToolsRegistry
    reg = object.__new__(ToolsRegistry)   # not ToolsRegistry.__new__: that returns the live singleton
    raw = {'name': 'zz_secret_probe', 'enabled': True, 'api_key': '${fred.api.key}'}
    store = {'config/tools/zz_secret_probe.json': json.loads(json.dumps(raw))}

    class Storage:
        def read_json(self, rel):
            return json.loads(json.dumps(store[rel]))

        def write_json(self, rel, data):
            store[rel] = data

        def get_modified_time(self, rel):
            return 0

    with mock.patch('sajha.tools.tools_registry.get_storage', return_value=Storage()), \
            mock.patch.object(reg, '_config_rel', return_value='config/tools/zz_secret_probe.json'), \
            mock.patch.object(reg, '_file_timestamps', {}, create=True):
        reg._save_enabled_flag('zz_secret_probe', False)
    assert store['config/tools/zz_secret_probe.json'] == {**raw, 'enabled': False}


# ── Change events: bulk loading publishes O(1) events ──────────────────────

class _CountingStore:
    def __init__(self):
        self.published = []

    def publish(self, channel, message):
        self.published.append((channel, message))

    def subscribe(self, channel, fn):
        return lambda: None


def _bare_registry():
    import logging
    import threading
    from sajha.tools.tools_registry import ToolsRegistry
    reg = object.__new__(ToolsRegistry)
    reg.tools, reg.tool_configs, reg.tool_errors = {}, {}, {}
    reg._tools_lock, reg.builtin_tools, reg.logger = threading.RLock(), {}, logging.getLogger('t')
    reg._properties_configurator = None
    reg._file_timestamps = {}
    return reg


def test_bulk_registration_publishes_once_and_relays_o1_events():
    from sajha.core.change_bus import CHANGES_CHANNEL, ChangeBus
    bus = ChangeBus()
    store = _CountingStore()
    bus.attach_store(store)
    reg = _bare_registry()
    with mock.patch('sajha.core.change_bus.get_change_bus', return_value=bus):
        with reg.bulk():
            for i in range(300):
                reg.register_tool(_schema_tool_named(f'zz_bulk_{i}'))
        first = len(store.published)
        assert 0 < first <= 3                       # one tools change: TOOLS, RESOURCES, catalog
        with reg.bulk():                            # the same tools again: nothing changed
            for i in range(300):
                reg.register_tool(_schema_tool_named(f'zz_bulk_{i}'))
        assert len(store.published) == first
        reg.unregister_tool('zz_not_there')         # no-op: no event
        assert len(store.published) == first
    assert all(ch == CHANGES_CHANNEL for ch, _ in store.published)
    bus.detach_store()


def test_bursts_outside_bulk_are_coalesced_on_the_store():
    from sajha.core.change_bus import ChangeBus
    bus = ChangeBus()
    bus.RELAY_WINDOW_SECONDS = 0.05
    store = _CountingStore()
    bus.attach_store(store)
    for _ in range(500):
        bus.tools_changed()
    assert len(store.published) == 3               # leading edge only, so far
    import time
    time.sleep(0.3)
    assert len(store.published) == 6               # plus one trailing relay per event kind
    bus.detach_store()


def test_registry_load_all_tools_publishes_once(tmp_path):
    from sajha.core.change_bus import ChangeBus
    bus = ChangeBus()
    store = _CountingStore()
    bus.attach_store(store)
    reg = _bare_registry()
    reg._config_prefix = 'config/tools'

    class Storage:
        def list_files(self, prefix, pattern):
            return [f'config/tools/calc_{n}.json' for n in ('percentage_change', 'future_value', 'present_value')]

    loaded = []
    with mock.patch('sajha.core.change_bus.get_change_bus', return_value=bus), \
            mock.patch('sajha.tools.tools_registry.get_storage', return_value=Storage()), \
            mock.patch.object(reg, 'load_tool_from_config',
                              side_effect=lambda rel: (loaded.append(rel),
                                                       reg.register_tool(_schema_tool_named(Path(rel).stem)))):
        reg.load_all_tools()
    assert len(loaded) == 3 and len(store.published) == 3
    bus.detach_store()


def _schema_tool_named(name):
    tool = _schema_tool({'type': 'object', 'properties': {}})
    tool._name = name
    return tool
