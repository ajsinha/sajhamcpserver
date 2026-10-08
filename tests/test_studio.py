# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
MCP Studio: generators, script-tool loading, and the admin action endpoints.

Generator tests write into a temp directory. The endpoint tests drive each creator
through preview/analyze → deploy → MCP tools/call → delete against the real
config/tools and sajha/tools/impl directories, using ``zz_test_*`` tool names that
are always cleaned up.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GUID = '12345678-1234-1234-1234-123456789012'
CODE = '''from sajha.studio import sajhamcptool

@sajhamcptool(description="Add two integers", category="Math")
def add(a: int, b: int = 2) -> dict:
    return {"sum": a + b}
'''


# ── Generators (temp dirs) ──────────────────────────────────────────────

@pytest.fixture
def gen_dirs(tmp_path, monkeypatch):
    """Temp config/impl/scripts dirs; tool JSON goes to the temp config dir too."""
    import sajha.core.storage as storage

    def _write(local_path, content):
        Path(local_path).write_text(content if isinstance(content, str) else json.dumps(content))
        return str(local_path)

    monkeypatch.setattr(storage, 'write_tool_config', _write)
    dirs = {k: tmp_path / k for k in ('cfg', 'impl', 'scripts')}
    for d in dirs.values():
        d.mkdir()
    return dirs


def _load(json_path, py_path):
    """Import the generated module from its file and build the tool the way the registry does."""
    config = json.loads(Path(json_path).read_text())
    module_path, class_name = config['implementation'].rsplit('.', 1)
    assert module_path.endswith(Path(py_path).stem)
    spec = importlib.util.spec_from_file_location(f'_studio_test_{Path(py_path).stem}', py_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    tool = getattr(module, class_name)(config)
    assert tool.name == config['name']
    assert isinstance(tool.get_input_schema(), dict) and isinstance(tool.get_output_schema(), dict)
    return tool


def test_python_code_generator(gen_dirs):
    from sajha.studio import CodeAnalyzer, ToolCodeGenerator
    tool_def = CodeAnalyzer().analyze(CODE)[0]
    ok, msg, j, p = ToolCodeGenerator(str(gen_dirs['cfg']), str(gen_dirs['impl'])).save_tool(tool_def, 'zz_add')
    assert ok, msg
    assert _load(j, p).execute({'a': 3}) == {'sum': 5}


def test_rest_generator_substitutes_path_params(gen_dirs):
    from sajha.studio import RESTToolGenerator, RESTToolDefinition
    g = RESTToolGenerator()
    g.config_dir, g.impl_dir = gen_dirs['cfg'], gen_dirs['impl']
    d = RESTToolDefinition(name='zz_rest', endpoint='https://api.example.com/items/{item_id}', method='GET',
                           description='Say "hi"', request_schema={'type': 'object', 'properties': {
                               'item_id': {'type': 'string'}}}, response_schema={},
                           api_key='k"ey', api_key_header='X-Key')
    ok, msg, j, p = g.save_tool(d)
    assert ok, msg
    tool = _load(j, p)
    resp = mock.Mock(status_code=200)
    resp.raise_for_status.return_value = None
    resp.json.return_value = {'ok': 1}
    with mock.patch('requests.request', return_value=resp) as req:
        out = tool.execute({'item_id': '42'})
    assert out['success'] and out['data'] == {'ok': 1}
    assert req.call_args.kwargs['url'] == 'https://api.example.com/items/42'
    assert req.call_args.kwargs['headers']['X-Key'] == 'k"ey'


def test_rest_generator_failure_leaves_no_files(gen_dirs):
    from sajha.studio import RESTToolGenerator, RESTToolDefinition
    g = RESTToolGenerator()
    g.config_dir, g.impl_dir = gen_dirs['cfg'], gen_dirs['impl']
    d = RESTToolDefinition(name='zz_rest_fail', endpoint='https://x', method='GET', description='d',
                           request_schema={}, response_schema={})
    with mock.patch.object(g, 'generate_python_implementation', side_effect=RuntimeError('boom')):
        ok, *_ = g.save_tool(d)
    assert not ok and not list(gen_dirs['cfg'].iterdir()) and not list(gen_dirs['impl'].iterdir())


def test_dbquery_generator_runs_query(gen_dirs, tmp_path):
    from sajha.studio import DBQueryToolGenerator, DBQueryToolDefinition, DBQueryParameter
    g = DBQueryToolGenerator()
    g.config_dir, g.impl_dir = gen_dirs['cfg'], gen_dirs['impl']
    d = DBQueryToolDefinition(name='zz_db', description='d', db_type='sqlite',
                              connection_string=str(tmp_path / 'x.db'),
                              query_template="SELECT {{n}} AS n, {{s}} AS s",
                              parameters=[DBQueryParameter(name='n', param_type='integer', description='n'),
                                          DBQueryParameter(name='s', param_type='string', description='s')])
    ok, msg, j, p = g.save_tool(d)
    assert ok, msg
    out = _load(j, p).execute({'n': 5, 's': "it's"})
    assert out['success'], out
    assert out['data'] == [{'n': 5, 's': "it's"}]


def test_script_generator_writes_loadable_dotted_implementation(gen_dirs):
    from sajha.studio import ScriptToolGenerator, ScriptToolConfig
    g = ScriptToolGenerator(str(gen_dirs['cfg']), str(gen_dirs['scripts']), str(gen_dirs['impl']))
    r = g.generate_tool(ScriptToolConfig(tool_name='zz_script', description='Echo """quoted"""',
                                         script_type='bash', script_content='echo "hi $1"'))
    assert r['success'], r
    config = json.loads(Path(r['config_path']).read_text())
    assert config['implementation'] == 'sajha.tools.impl.zz_script_script_tool.ZzScriptScriptTool'
    assert config['inputSchema']['properties']['args']['type'] == 'array'
    out = _load(r['config_path'], r['wrapper_path']).execute({'args': ['there']})
    assert out == {'stdout': 'hi there\n', 'stderr': '', 'exit_code': 0, 'success': True}
    assert set(map(os.path.basename, g.delete_tool('zz_script')['deleted_files'])) == {
        'zz_script.json', 'zz_script_script_tool.py', 'zz_script.sh'}


@pytest.mark.parametrize('kind', ['powerbi', 'powerbidax', 'livelink'])
def test_config_creators_generate_registry_compatible_tools(gen_dirs, kind):
    from sajha import studio
    if kind == 'powerbi':
        gen = studio.PowerBIToolGenerator(str(gen_dirs['cfg']), str(gen_dirs['impl']))
        cfg = studio.PowerBIToolConfig(tool_name='zz_pbi', description='d "q"', report_name='r',
                                       workspace_id=GUID, report_id=GUID, tenant_id=GUID, client_id=GUID)
    elif kind == 'powerbidax':
        gen = studio.PowerBIDAXToolGenerator(str(gen_dirs['cfg']), str(gen_dirs['impl']))
        cfg = studio.PowerBIDAXToolConfig(tool_name='zz_dax', description='d', dataset_name='ds',
                                          workspace_id=GUID, dataset_id=GUID, dax_query='EVALUATE T',
                                          tenant_id=GUID, client_id=GUID)
    else:
        gen = studio.LiveLinkToolGenerator(str(gen_dirs['cfg']), str(gen_dirs['impl']))
        cfg = studio.LiveLinkToolConfig(tool_name='zz_ll', description='d',
                                        server_url='https://ll.example.com/otcs/cs.exe')
    assert gen.validate_config(cfg) == []
    r = gen.generate_tool(cfg)
    assert r['success'], r
    tool = _load(r['files']['json_config'], r['files']['python_impl'])
    # No credentials in the environment: execute() must return an error result, not raise
    with mock.patch.dict(os.environ, {}, clear=False):
        for var in ('POWERBI_CLIENT_SECRET', 'LIVELINK_USERNAME', 'LIVELINK_PASSWORD'):
            os.environ.pop(var, None)
        with mock.patch('requests.request', side_effect=OSError('no network')), \
                mock.patch('requests.get', side_effect=OSError('no network')), \
                mock.patch('requests.post', side_effect=OSError('no network')):
            out = tool.execute({})
    assert isinstance(out, dict) and out.get('success') is False


def test_dax_parameter_substitution_escapes_quotes(gen_dirs):
    from sajha.studio import PowerBIDAXToolGenerator, PowerBIDAXToolConfig
    gen = PowerBIDAXToolGenerator(str(gen_dirs['cfg']), str(gen_dirs['impl']))
    r = gen.generate_tool(PowerBIDAXToolConfig(tool_name='zz_dax2', description='d', dataset_name='ds',
                                               workspace_id=GUID, dataset_id=GUID,
                                               dax_query='EVALUATE FILTER(T, T[r] = @region)',
                                               tenant_id=GUID, client_id=GUID))
    tool = _load(r['files']['json_config'], r['files']['python_impl'])
    assert tool._substitute_parameters('X = @region', {'region': 'a"b'}) == 'X = "a""b"'


def test_registry_loads_legacy_object_implementation(tmp_path, monkeypatch):
    """Script tools written before the fix have "implementation": {...}; they must still load.
    This checks the in-process compatibility shim, so the sandbox (which would run the
    script itself, tests/test_sandbox.py) is switched off for it."""
    monkeypatch.setenv('SAJHA_SANDBOX_ENFORCE_FOR_GENERATED_TOOLS', 'false')
    from sajha.tools.tools_registry import ToolsRegistry
    legacy = tmp_path / 'zz_legacy_script_tool.py'
    legacy.write_text('''
from sajha.tools.base_mcp_tool import BaseMCPTool
class ZzLegacyScriptTool(BaseMCPTool):
    def __init__(self, tool_config):
        super().__init__(tool_config)
    async def execute(self, arguments):
        return {"echo": arguments.get("args")}
TOOL_CLASS = ZzLegacyScriptTool
''')
    spec = importlib.util.spec_from_file_location('sajha.tools.impl.zz_legacy_script_tool', legacy)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, 'sajha.tools.impl.zz_legacy_script_tool', module)

    # object.__new__, not ToolsRegistry.__new__: the singleton's __new__ would hand back the live
    # registry, and the line below would empty it for every later test.
    reg = object.__new__(ToolsRegistry)
    import logging
    import threading
    reg.tools, reg.tool_configs, reg.tool_errors = {}, {}, {}
    reg._tools_lock, reg.builtin_tools, reg.logger = threading.RLock(), {}, logging.getLogger('t')
    reg._properties_configurator = None
    reg.register_tool_from_dict({'name': 'zz_legacy', 'description': 'd',
                                 'input_schema': {'type': 'object', 'properties': {'args': {'type': 'array'}}},
                                 'implementation': {'type': 'script', 'script_file': 'zz_legacy.sh'}})
    assert 'zz_legacy' in reg.tools, reg.tool_errors
    tool = reg.tools['zz_legacy']
    assert tool.get_input_schema()['properties']['args']['type'] == 'array'
    assert tool.execute({'args': ['x']}) == {'echo': ['x']}


# ── Endpoints (live app) ────────────────────────────────────────────────

@pytest.fixture(scope='module')
def studio():
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        r = c.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'})
        assert r.status_code == 200
        headers = {'Authorization': f"Bearer {r.json()['token']}"}
        created = []
        yield c, headers, created
        # Clean up anything a failed test left behind
        for name in created:
            c.post('/admin/studio/delete', json={'tool_name': name}, headers=headers)
        for pattern in ('config/tools/zz_test_*', 'sajha/tools/impl/*zz_test_*', 'config/scripts/zz_test_*'):
            for f in ROOT.glob(pattern):
                f.unlink()


def _mcp_call(c, headers, name, arguments):
    r = c.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                             'params': {'name': name, 'arguments': arguments}}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _mcp_result(resp):
    assert 'result' in resp, resp
    res = resp['result']
    if res.get('structuredContent') is not None:
        return res['structuredContent']
    return json.loads(res['content'][0]['text'])


def _deploy_call_delete(studio, name, preview_url, deploy_url, payload, arguments, check):
    c, headers, created = studio
    created.append(name)
    if preview_url:
        r = c.post(preview_url, json=payload, headers=headers)
        assert r.status_code == 200 and r.json()['success'], r.text
    r = c.post(deploy_url, json=payload, headers=headers)
    assert r.status_code == 200 and r.json()['success'], r.text
    from sajha.app import tools_registry
    assert name in tools_registry.tools, tools_registry.tool_errors.get(name)
    # A second deploy of the same name is refused
    r = c.post(deploy_url, json=payload, headers=headers)
    assert r.status_code == 400 and 'already exists' in r.json()['error']
    check(_mcp_call(c, headers, name, arguments))
    r = c.post('/admin/studio/delete', json={'tool_name': name}, headers=headers)
    assert r.status_code == 200 and r.json()['success'] and r.json()['deleted_files'], r.text
    assert name not in tools_registry.tools
    assert not (ROOT / 'config' / 'tools' / f'{name}.json').exists()
    assert not list((ROOT / 'sajha' / 'tools' / 'impl').glob(f'*{name}*.py'))
    created.remove(name)


def test_python_creator_end_to_end(studio):
    c, headers, _ = studio
    r = c.post('/admin/studio/analyze', json={'code': CODE, 'tool_name': 'zz_test_add'}, headers=headers)
    body = r.json()
    assert body['success'] and body['function_name'] == 'add'
    assert [p['name'] for p in body['parameters']] == ['a', 'b']
    _deploy_call_delete(studio, 'zz_test_add', None, '/admin/studio/deploy',
                        {'code': CODE, 'tool_name': 'zz_test_add'}, {'a': 40},
                        lambda resp: _mcp_result(resp) == {'sum': 42} or pytest.fail(str(resp)))


def test_rest_creator_end_to_end(studio):
    payload = {'name': 'zz_test_rest', 'endpoint': 'http://127.0.0.1:9/nothing', 'method': 'GET',
               'description': 'Unreachable endpoint', 'request_schema': {'type': 'object', 'properties': {}},
               'response_format': 'json', 'timeout': 2}

    def check(resp):
        out = _mcp_result(resp) if 'result' in resp else resp
        assert 'Request failed' in json.dumps(out) or 'error' in json.dumps(out).lower()
    _deploy_call_delete(studio, 'zz_test_rest', '/admin/studio/rest/preview', '/admin/studio/rest/deploy',
                        payload, {}, check)


@pytest.mark.parametrize('fmt,body,expected', [
    ('json', '{"a": 1}', {'a': 1}),
    ('text', 'plain words', 'plain words'),
    ('csv', 'x,y\n1,2\n', [{'x': 1, 'y': 2}]),
])
def test_rest_generator_parses_response_formats(gen_dirs, fmt, body, expected):
    import requests
    from sajha.studio import RESTToolGenerator, RESTToolDefinition
    g = RESTToolGenerator()
    g.config_dir, g.impl_dir = gen_dirs['cfg'], gen_dirs['impl']
    ok, msg, j, p = g.save_tool(RESTToolDefinition(name=f'zz_fmt_{fmt}', endpoint='https://x.test/r', method='GET',
                                                    description='d', request_schema={}, response_schema={},
                                                    response_format=fmt))
    assert ok, msg
    resp = requests.Response()
    resp.status_code, resp._content, resp.encoding = 200, body.encode(), 'utf-8'
    with mock.patch('requests.request', return_value=resp):
        out = _load(j, p).execute({})
    assert out['success'] and out['data'] == expected, out


def test_dbquery_creator_end_to_end(studio, tmp_path):
    payload = {'name': 'zz_test_db', 'description': 'Square a number', 'db_type': 'duckdb',
               'connection_string': ':memory:', 'query_template': 'SELECT {{n}} * {{n}} AS sq',
               'parameters': [{'name': 'n', 'param_type': 'integer', 'description': 'n', 'required': True}]}
    _deploy_call_delete(studio, 'zz_test_db', '/admin/studio/dbquery/preview', '/admin/studio/dbquery/deploy',
                        payload, {'n': 7},
                        lambda resp: _mcp_result(resp)['data'] == [{'sq': 49}] or pytest.fail(str(resp)))


def test_script_creator_end_to_end(studio):
    payload = {'tool_name': 'zz_test_script', 'description': 'Echo args', 'script_type': 'bash',
               'script_content': 'echo "got $1"'}
    _deploy_call_delete(studio, 'zz_test_script', '/admin/studio/script/preview', '/admin/studio/script/deploy',
                        payload, {'args': ['x']},
                        lambda resp: _mcp_result(resp)['stdout'] == 'got x\n' or pytest.fail(str(resp)))
    assert not list((ROOT / 'config' / 'scripts').glob('zz_test_script.*'))


def _expect_error_result(resp):
    """Credential-backed tools have no backend in tests: the call must return an error, not crash."""
    assert 'result' in resp or 'error' in resp, resp
    text = json.dumps(resp)
    assert 'success' in text or 'error' in text.lower()


@pytest.mark.parametrize('kind,payload', [
    ('powerbi', {'tool_name': 'zz_test_pbi', 'description': 'Report', 'report_name': 'Sales',
                 'workspace_id': GUID, 'report_id': GUID, 'tenant_id': GUID, 'client_id': GUID}),
    ('powerbidax', {'tool_name': 'zz_test_dax', 'description': 'DAX', 'dataset_name': 'Sales',
                    'workspace_id': GUID, 'dataset_id': GUID, 'dax_query': 'EVALUATE Sales',
                    'tenant_id': GUID, 'client_id': GUID}),
    ('livelink', {'tool_name': 'zz_test_ll', 'description': 'Docs',
                  'server_url': 'http://127.0.0.1:9/otcs/cs.exe', 'auth_type': 'basic'}),
])
def test_config_creators_end_to_end(studio, kind, payload):
    with mock.patch.dict(os.environ, {'LIVELINK_USERNAME': 'u', 'LIVELINK_PASSWORD': 'p'}):
        _deploy_call_delete(studio, payload['tool_name'], f'/admin/studio/{kind}/preview',
                            f'/admin/studio/{kind}/deploy', payload, {}, _expect_error_result)


def test_sharepoint_creator_end_to_end(studio):
    payload = {'name': 'zz_test_sp', 'description': 'Docs', 'tool_type': 'documents',
               'site_url': 'https://example.sharepoint.com/sites/x', 'auth_type': 'client_credentials',
               'tenant_id': 't', 'client_id': 'c', 'client_secret': 's3cret', 'allowed_operations': ['list']}
    c, headers, _ = studio
    r = c.post('/admin/studio/sharepoint/preview', json=payload, headers=headers)
    assert r.json()['config']['authentication']['client_secret'] == '***hidden***'
    _deploy_call_delete(studio, 'zz_test_sp', None, '/admin/studio/sharepoint/deploy', payload,
                        {'operation': 'list'}, _expect_error_result)


def test_olap_dataset_deploy_and_delete(studio, tmp_path, monkeypatch):
    """Runs against a temp copy of config/olap: deploy/delete re-serialise the JSON files, and a
    test must never rewrite repository config (not even transiently)."""
    import shutil
    from sajha.routes import studio_routes
    c, headers, _ = studio
    olap = tmp_path / 'olap'
    shutil.copytree(ROOT / 'config' / 'olap', olap)
    monkeypatch.setattr(studio_routes, 'OLAP_DIR', olap)
    repo_olap = {f: f.read_bytes() for f in (ROOT / 'config' / 'olap').glob('*.json')}
    payload = {'name': 'zz_test_ds', 'source_table': 'sales', 'dimensions': ['zz_test_dim'],
               'measures': ['zz_test_measure'],
               'dimension_definitions': [{'name': 'zz_test_dim', 'column': 'region', 'type': 'standard'}],
               'measure_definitions': [{'name': 'zz_test_measure', 'expression': 'SUM(amount)',
                                        'format': 'number', 'description': ''}]}
    r = c.post('/admin/studio/olap/deploy', json=payload, headers=headers)
    try:
        assert r.json()['success'], r.text
        ds = json.loads((olap / 'datasets.json').read_text())['datasets']['zz_test_ds']
        assert ds['created_by'] == 'MCP Studio' and ds['display_name'] == 'zz_test_ds'
        assert c.post('/admin/studio/olap/deploy', json=payload, headers=headers).json()['success'] is False
        dims = json.loads((olap / 'dimensions.json').read_text())['dimensions']
        assert dims['zz_test_dim']['column'] == 'region'
        assert json.loads((olap / 'measures.json').read_text())['measures']['zz_test_measure']['expression'] == 'SUM(amount)'
    finally:
        r = c.post('/admin/studio/olap/delete', json={'name': 'zz_test_ds'}, headers=headers)
    assert r.json()['success'], r.text
    assert 'zz_test_ds' not in json.loads((olap / 'datasets.json').read_text())['datasets']
    assert 'zz_test_dim' not in json.loads((olap / 'dimensions.json').read_text())['dimensions']
    assert 'zz_test_measure' not in json.loads((olap / 'measures.json').read_text())['measures']
    # Shipped datasets cannot be deleted from Studio
    assert c.post('/admin/studio/olap/delete', json={'name': 'customer_olap'}, headers=headers).status_code == 403
    assert {f: f.read_bytes() for f in (ROOT / 'config' / 'olap').glob('*.json')} == repo_olap


def test_delete_refuses_tools_studio_did_not_create(studio):
    c, headers, _ = studio
    from sajha.app import tools_registry
    builtin = next(n for n in tools_registry.tools if (ROOT / 'config' / 'tools' / f'{n}.json').exists())
    r = c.post('/admin/studio/delete', json={'tool_name': builtin}, headers=headers)
    assert r.status_code == 403
    assert builtin in tools_registry.tools and (ROOT / 'config' / 'tools' / f'{builtin}.json').exists()


def test_invalid_names_and_conflicts_rejected(studio):
    c, headers, _ = studio
    for bad in ('../evil', 'A', 'x' * 70, 'Bad-Name'):
        r = c.post('/admin/studio/analyze', json={'code': CODE, 'tool_name': bad}, headers=headers)
        assert r.status_code == 400 and not r.json()['success']
    from sajha.app import tools_registry
    existing = next(iter(tools_registry.tools))
    r = c.post('/admin/studio/script/preview', json={'tool_name': existing, 'description': 'd',
                                                     'script_content': 'echo'}, headers=headers)
    assert r.status_code == 400 and 'already exists' in r.json()['error']


def test_actions_require_admin(studio):
    c, _, _ = studio
    r = c.post('/admin/studio/analyze', json={'code': CODE, 'tool_name': 'zz_test_x'}, follow_redirects=False)
    assert r.status_code in (302, 401, 403)
    r = c.post('/admin/studio/delete', json={'tool_name': 'zz_test_x'}, follow_redirects=False)
    assert r.status_code in (302, 401, 403)


def test_pages_render_working_links(studio):
    c, headers, _ = studio
    sp = c.get('/studio/sharepoint', headers=headers).text
    assert '/admin/studio/sharepoint/deploy' in sp and 'studio.deploy_sharepoint_tool' not in sp
    assert 'tools.list_tools' not in sp
    assert 'href="/studio/sharepoint"' in c.get('/studio', headers=headers).text  # sub-nav entry
    examples = c.get('/studio/examples', headers=headers).text
    assert 'Simple Calculator' in examples and 'Text Analyzer' in examples
    assert '@sajhamcptool' in c.get('/studio', headers=headers).text  # sample code in the editor
