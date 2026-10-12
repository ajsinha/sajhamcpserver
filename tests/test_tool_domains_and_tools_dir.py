# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The tools directory follows ``config.tools.dir``; the creators' Folder field (Unfiled = the root, a new
name creates the folder on first write); tool domains (the Domains page, ``/tools?domain=``, the landing
page's groups and chips).

The end-to-end part points ``config.tools.dir`` (env SAJHA_CONFIG_TOOLS_DIR) at a folder of a temporary
storage base and drives the registry, every creator, Import JSON, API Import, the Tools page and the
Domains page against it: the repository's config/tools is never touched.
"""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from tests.tool_config_files import ROOT, TOOLS, tool_file

SAMPLE = 'calc_percentage_change'
HOME = 'zz_tools_home'                         # config.tools.dir, relative to the temporary storage base
GUID = '12345678-1234-1234-1234-123456789012'
CODE = '''from sajha.studio import sajhamcptool

@sajhamcptool(description="Add two integers", category="Math")
def add(a: int, b: int = 2) -> dict:
    return {"sum": a + b}
'''


def _cfg(name: str) -> dict:
    cfg = json.loads(tool_file(SAMPLE).read_text(encoding='utf-8'))
    cfg['name'] = name
    return cfg


def _snapshot():
    return {str(p.relative_to(TOOLS)): p.stat().st_mtime_ns for p in TOOLS.rglob('*') if p.is_file()}


# ── unit: folder names, labels, domain summaries ─────────────────────────

def test_unfiled_means_the_root_and_is_reserved():
    from sajha.tools.tool_files import clean_folder, folder_problem, is_unfiled, slug_folder
    for v in ('Unfiled', 'unfiled', ' UNFILED ', '', None, '/'):
        assert clean_folder(v) == ''
    assert is_unfiled('Unfiled') and not is_unfiled('') and not is_unfiled('fmp')
    assert folder_problem('unfiled', check_tools=False) and slug_folder('Unfiled') == ''
    assert clean_folder('fmp') == 'fmp'


def test_domain_labels_map_then_title_case():
    from sajha.tools.domains import UNFILED_KEY, domain_label, query_key
    assert domain_label('fmp') == 'Financial Modeling Prep' and domain_label('qlrisk') == 'QLRisk'
    assert domain_label('bank_of_canada') == 'Bank of Canada'          # not mapped: title case
    assert domain_label('zz_some-thing') == 'Zz Some Thing'
    assert domain_label(UNFILED_KEY) == 'Unfiled'
    assert query_key('Unfiled') == UNFILED_KEY and query_key('fred') == 'fred' and query_key(None) == ''


class _Reg:
    folders = {'zz_a1': 'zz_fa', 'zz_a2': 'zz_fa', 'zz_b1': 'zz_fb', 'zz_root': ''}

    def tool_folder(self, name):
        return self.folders.get(name)


def test_summarize_counts_unfiled_proxied_and_visibility():
    from sajha.tools.domains import summarize
    tools = [{'name': n} for n in ('zz_a1', 'zz_a2', 'zz_b1', 'zz_root', 'wx__forecast')]
    rows = {d['key']: d for d in summarize(_Reg(), tools)}
    assert rows['zz_fa']['count'] == 2 and rows['zz_fa']['kind'] == 'folder' and rows['zz_fa']['folder'] == 'zz_fa'
    assert rows['__unfiled__']['label'] == 'Unfiled' and rows['__unfiled__']['href'] == '/tools?domain=unfiled'
    assert rows['wx']['kind'] == 'proxied' and rows['wx']['folder'] is None
    assert list(rows)[0] == 'zz_fa'                                      # biggest first
    seen = {d['key']: d['count'] for d in summarize(_Reg(), tools, visible=lambda n: n != 'zz_a2')}
    assert seen['zz_fa'] == 1


def test_live_tool_groups_group_by_folder_with_prefix_map():
    from sajha.web.help_catalog import live_tool_groups

    class T:
        def __init__(self):
            self.config = {'enabled': True, 'description': 'd'}

    reg = _Reg()
    reg.tools = {n: T() for n in ('zz_a1', 'zz_a2', 'zz_b1', 'zz_root')}
    live = live_tool_groups(reg, with_names=True, visible=lambda n: n != 'zz_b1')
    groups = {g['name']: g for g in live['groups']}
    assert set(groups) == {'zz_fa', 'zz_fb', '__unfiled__'} and live['total_groups'] == 3
    assert groups['zz_fa']['tool_count'] == 2 and groups['zz_fa']['href'] == '/tools?domain=zz_fa'
    assert groups['zz_fb']['tool_count'] == 1 and groups['zz_fb']['tools'] == []      # counted, not named
    assert live['prefixes']['zz'] == 'zz_fa'                                          # most of zz_* are there


# ── end to end with config.tools.dir pointing at a temporary folder ──────

@pytest.fixture(scope='module')
def client():
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        r = c.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'})
        assert r.status_code == 200
        yield c, {'Authorization': f"Bearer {r.json()['token']}"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """config.tools.dir = HOME on a local storage base at tmp_path, a registry over it as the app's."""
    import sajha.app as app_mod
    import sajha.core.storage as storage
    from sajha.tools.tools_registry import ToolsRegistry
    monkeypatch.setenv('SAJHA_CONFIG_TOOLS_DIR', HOME)
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path)))
    monkeypatch.setattr(ToolsRegistry, 'start_monitoring', lambda self: None)
    monkeypatch.setattr(ToolsRegistry, 'start_retrying', lambda self: None)
    base = tmp_path / HOME
    (base / 'zz_calc').mkdir(parents=True)
    (base / 'zz_calc' / 'zz_e2e_in_folder.json').write_text(json.dumps(_cfg('zz_e2e_in_folder')))
    (base / 'zz_e2e_at_root.json').write_text(json.dumps(_cfg('zz_e2e_at_root')))
    before = _snapshot()
    monkeypatch.setattr(ToolsRegistry, '_instance', None)
    reg = ToolsRegistry()                                   # no directory given: config.tools.dir
    monkeypatch.setattr(app_mod, 'tools_registry', reg)
    yield reg, base
    after = _snapshot()
    assert after == before, 'the repository config/tools changed'


def test_the_registry_reads_the_configured_tools_directory(home):
    reg, base = home
    from sajha.tools.tool_files import default_prefix
    assert default_prefix() == HOME and reg._config_prefix == HOME
    assert {'zz_e2e_in_folder', 'zz_e2e_at_root'} <= set(reg.tools)
    assert SAMPLE not in reg.tools                          # nothing from config/tools
    assert reg.tool_folder('zz_e2e_in_folder') == 'zz_calc' and reg.tool_folder('zz_e2e_at_root') == ''
    from sajha.ai.ask_tool import config_rel
    assert config_rel().startswith(HOME + '/')


def _api_import_body(name):
    from tests.test_api_import import PETSTORE
    return {'kind': 'openapi', 'text': PETSTORE, 'prefix': name, 'base_url': 'http://127.0.0.1:9/v1',
            'selected': ['GET /pets']}


CREATORS = [
    ('python', '/admin/studio/deploy', lambda n: {'code': CODE, 'tool_name': n}),
    ('rest', '/admin/studio/rest/deploy', lambda n: {
        'name': n, 'endpoint': 'http://127.0.0.1:9/x', 'method': 'GET', 'description': 'd',
        'request_schema': {'type': 'object', 'properties': {}}, 'response_format': 'json', 'timeout': 2}),
    ('dbquery', '/admin/studio/dbquery/deploy', lambda n: {
        'name': n, 'description': 'Square', 'db_type': 'duckdb', 'connection_string': ':memory:',
        'query_template': 'SELECT {{n}} * {{n}} AS sq',
        'parameters': [{'name': 'n', 'param_type': 'integer', 'description': 'n', 'required': True}]}),
    ('script', '/admin/studio/script/deploy', lambda n: {
        'tool_name': n, 'description': 'Echo', 'script_type': 'bash', 'script_content': 'echo hi'}),
    ('powerbi', '/admin/studio/powerbi/deploy', lambda n: {
        'tool_name': n, 'description': 'Report', 'report_name': 'Sales', 'workspace_id': GUID,
        'report_id': GUID, 'tenant_id': GUID, 'client_id': GUID}),
    ('powerbidax', '/admin/studio/powerbidax/deploy', lambda n: {
        'tool_name': n, 'description': 'DAX', 'dataset_name': 'Sales', 'workspace_id': GUID,
        'dataset_id': GUID, 'dax_query': 'EVALUATE Sales', 'tenant_id': GUID, 'client_id': GUID}),
    ('livelink', '/admin/studio/livelink/deploy', lambda n: {
        'tool_name': n, 'description': 'Docs', 'server_url': 'http://127.0.0.1:9/otcs/cs.exe', 'auth_type': 'basic'}),
    ('sharepoint', '/admin/studio/sharepoint/deploy', lambda n: {
        'name': n, 'description': 'Docs', 'tool_type': 'documents', 'site_url': 'https://example.sharepoint.com/sites/x',
        'auth_type': 'client_credentials', 'tenant_id': 't', 'client_id': 'c', 'client_secret': 's',
        'allowed_operations': ['list']}),
    ('llm', '/admin/studio/llm/deploy', lambda n: {'form': {
        'name': n, 'description': 'Classifies a support message into a queue.', 'mode': 'classify',
        'instructions': 'system_prompt', 'system_prompt': 'billing: money. technical: bugs.',
        'template': 'Classify this message:\n\n{{input.message}}', 'labels': ['billing', 'technical', 'other']}}),
    ('json', '/admin/studio/json/deploy', lambda n: {'config': _cfg(n)}),
]


@pytest.mark.parametrize('kind,url,body', CREATORS, ids=[c[0] for c in CREATORS])
def test_each_creator_creates_a_new_folder_on_first_write_and_unfiled_is_the_root(client, home, kind, url, body):
    c, h = client
    reg, base = home
    impl = ROOT / 'sajha' / 'tools' / 'impl'
    names = {'new': f'zz_e2e_{kind}_new', 'root': f'zz_e2e_{kind}_root'}
    try:
        with mock.patch.dict(os.environ, {'LIVELINK_USERNAME': 'u', 'LIVELINK_PASSWORD': 'p'}):
            folder = f'zz_new_{kind}'
            assert not (base / folder).exists()
            r = c.post(url, json={**body(names['new']), 'folder': folder}, headers=h)
            assert r.status_code == 200 and r.json()['success'], r.text
            assert (base / folder / f"{names['new']}.json").is_file()            # the folder was created
            assert reg.tool_folder(names['new']) == folder
            r = c.post(url, json={**body(names['root']), 'folder': 'Unfiled'}, headers=h)
            assert r.status_code == 200 and r.json()['success'], r.text
            assert (base / f"{names['root']}.json").is_file()                    # Unfiled: the root
            assert reg.tool_folder(names['root']) == ''
    finally:
        for n in names.values():
            c.post('/admin/studio/delete', json={'tool_name': n}, headers=h)
            for f in impl.glob(f'*{n}*'):
                f.unlink()
            for f in (ROOT / 'config' / 'scripts').glob(f'{n}.*'):
                f.unlink()


def test_api_import_files_new_folder_and_unfiled(client, home, monkeypatch):
    monkeypatch.setenv('SAJHA_API_IMPORT_ALLOW_LOCALHOST', 'true')
    c, h = client
    reg, base = home
    r = c.post('/admin/studio/api-import/deploy', json={**_api_import_body('zz_e2e_pets'), 'folder': 'zz_new_api'},
               headers=h)
    assert r.status_code == 200 and r.json()['success'], r.text
    assert list((base / 'zz_new_api').glob('zz_e2e_pets_*.json'))
    r = c.post('/admin/studio/api-import/deploy', json={**_api_import_body('zz_e2e_cats'), 'folder': 'Unfiled'},
               headers=h)
    assert r.status_code == 200 and r.json()['success'], r.text
    assert list(base.glob('zz_e2e_cats_*.json')) and not (base / 'zz_e2e_cats').exists()


def test_the_object_store_creates_a_new_folder_on_first_write(tmp_path, monkeypatch):
    import sajha.core.storage as storage
    from sajha.tools.tool_files import write_config, writing_into
    from tests.test_tool_folders import _memory_backend
    mem = _memory_backend(tmp_path / 'cache')
    monkeypatch.setattr(storage, '_storage', mem)
    monkeypatch.setenv('SAJHA_CONFIG_TOOLS_DIR', HOME)
    from sajha.tools.tools_registry import ToolsRegistry
    monkeypatch.setattr(ToolsRegistry, '_instance', None)
    with writing_into('zz_brand_new'):
        rel = storage.write_tool_config('zz_obj_new.json', _cfg('zz_obj_new'))
    assert rel == f'{HOME}/zz_brand_new/zz_obj_new.json' and rel in mem.objs
    assert write_config('zz_obj_root', _cfg('zz_obj_root'), 'Unfiled') == f'{HOME}/zz_obj_root.json'


def test_tools_page_domain_filter_and_domains_page(client, home):
    c, h = client
    reg, base = home
    page = c.get('/tools?domain=zz_calc', headers=h).text
    assert 'const preDomain = "zz_calc";' in page and 'zz_e2e_in_folder' in page and SAMPLE not in page
    assert 'const preDomain = "__unfiled__";' in c.get('/tools?domain=Unfiled', headers=h).text
    dom = c.get('/tools/domains', headers=h)
    assert dom.status_code == 200
    assert 'href="/tools?domain=zz_calc"' in dom.text and 'href="/tools?domain=unfiled"' in dom.text
    assert 'Zz Calc' in dom.text and 'root of ' + HOME in dom.text
    assert c.get('/tools/domains', follow_redirects=False).status_code in (302, 303, 401)


def test_domains_page_respects_visibility(client, home, monkeypatch):
    c, h = client
    import sajha.auth.access as access

    class Only:
        def unrestricted(self):
            return False

        def can_see(self, name):
            return name == 'zz_e2e_at_root'

    monkeypatch.setattr(access, 'policy_for', lambda auth: Only())
    text = c.get('/tools/domains', headers=h).text
    assert 'href="/tools?domain=unfiled"' in text and 'href="/tools?domain=zz_calc"' not in text


def test_landing_groups_by_domain_with_chips(client, home):
    from fastapi.testclient import TestClient
    text = TestClient(client[0].app).get('/').text           # anonymous: no lifespan, no cookie
    assert 'tools across 2 domains, ready out of the box' in text
    assert 'Out of the box' in text
    assert 'href="/login?next=%2Ftools%3Fdomain%3Dzz_calc"' in text
    assert 'href="/login?next=%2Ftools%3Fdomain%3Dunfiled"' in text
    data = json.loads(text.split('id="lpData">', 1)[1].split('</script>', 1)[0])
    assert {g[0] for g in data['groups']} == {'zz_calc', '__unfiled__'} and data['prefixes']['zz'] in ('zz_calc', '__unfiled__')


def test_unloading_a_tool_forgets_only_a_module_studio_generated():
    """Deleting an LLM tool once removed sajha.ai.llm_tools from sys.modules; its re-import made a second
    copy of the package without its submodules as attributes, and a later test failed by order."""
    from sajha.routes.studio_routes import _studio_module
    assert not _studio_module('sajha.ai.llm_tools', 'llm')
    assert not _studio_module('sajha.tools.impl.calc_tools', 'calc')
    assert _studio_module('sajha.tools.impl.rest_zz_x', 'zz_x')
    assert _studio_module('sajha.tools.impl.zz_x_script_tool', 'zz_x')
    assert not _studio_module(None, 'zz_x')
