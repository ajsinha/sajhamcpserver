# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Storage, finished (Roadmap L1): DuckDB reads a ``storage://`` data folder by staging files,
Studio-generated modules and scripts travel through the storage backend and are materialised
locally on load, plugins are mirrored from a bucket, workflow file triggers poll at once on a
bucket event, and the migrated subsystems keep no direct ``open('config/...')``. An in-memory
object store stands in for S3, Azure Blob and GCS (the emulator tests are in
tests/test_storage_emulators.py).
"""

import json
import re
import sys
from pathlib import Path

import pytest

import sajha.core.storage as storage
from tests.test_storage_events import Memory

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def bucket(tmp_path, monkeypatch):
    backend = Memory(tmp_path / 'cache')
    monkeypatch.setattr(storage, '_storage', backend)
    return backend


# ── DuckDB on the storage backend ────────────────────────────────────────────

@pytest.fixture
def duck(bucket, tmp_path, monkeypatch):
    from sajha.tools.impl import duckdb_olap_tools_refactored as mod
    bucket.write_text('data/duck/orders.csv', 'id,amount\n1,5.5\n2,7.0\n')
    bucket.write_text('data/duck/notes.txt', 'not data\n')
    bucket.write_text('data/duck/sub/deeper.csv', 'x\n1\n')            # only direct children load
    stage = tmp_path / 'stage'
    settings = {'data.duckdb.stage_dir': str(stage)}
    monkeypatch.setattr('sajha.core.config._get', lambda k, d=None: settings.get(k, d))
    d = 'storage://data/duck'
    tools = {n: cls({'name': n, 'data_directory': d, 'auto_refresh_enabled': False})
             for n, cls in mod.DUCKDB_TOOLS.items()}
    yield mod, tools, settings, stage
    with mod.DuckDbSandbox._instances_lock:
        box = mod.DuckDbSandbox._instances.pop(d, None)
    if box is not None:
        from sajha.core.storage_events import remove_path_listener
        remove_path_listener(box._on_storage_paths)


def test_duckdb_reads_a_storage_folder_through_a_staging_copy(duck):
    mod, tools, _, stage = duck
    r = tools['duckdb_query'].execute({'sql_query': 'SELECT SUM(amount) AS s FROM orders'})
    assert r['rows'] == [{'s': 12.5}]
    files = mod.scan_data_files('storage://data/duck')
    assert [f['filename'] for f in files] == ['orders.csv'] and files[0]['source'] == 'storage'
    assert not any(stage.rglob('*.csv'))                    # staged copies are deleted after the load
    with pytest.raises(Exception):                          # the sandbox still has no file access
        tools['duckdb_query'].execute({'sql_query': "SELECT * FROM read_text('/etc/hostname')"})


def test_duckdb_storage_change_detection_and_push(duck, bucket):
    mod, tools, _, _ = duck
    box = tools['duckdb_query'].sandbox
    assert not box.changed()
    bucket.write_text('data/duck/orders.csv', 'id,amount\n1,1.0\n')
    assert box.changed()
    box.reload()
    assert not box.changed()
    bucket.write_text('data/duck/more.csv', 'k\n1\n')
    import threading
    done = threading.Event()
    orig = box.reload
    box.reload = lambda: (orig(), done.set())
    from sajha.core.storage_events import emit_paths
    emit_paths(['data/duck/more.csv'])
    assert done.wait(10)
    assert 'more.csv' in box.file_states


def test_duckdb_staging_size_limits(duck, bucket):
    mod, tools, settings, _ = duck
    settings['data.duckdb.stage_max_file_mb'] = 0.00001       # ~10 bytes: orders.csv is larger
    states = tools['duckdb_query'].sandbox.reload()
    assert states == {}
    settings.pop('data.duckdb.stage_max_file_mb')
    bucket.write_text('data/duck/second.csv', 'id,amount\n3,1.0\n')
    settings['data.duckdb.stage_max_total_mb'] = 30 / (1024 * 1024)   # room for one file only
    assert len(tools['duckdb_query'].sandbox.reload()) == 1


def test_storage_data_directory_refuses_traversal():
    from sajha.tools.impl import duckdb_olap_tools_refactored as mod
    for bad in ('storage://', 'storage://../x', 'storage://a/../../b'):
        with pytest.raises(ValueError):
            mod.storage_prefix(bad)
    assert mod.storage_prefix('./data/duckdb') is None


# ── Studio modules and scripts ───────────────────────────────────────────────

@pytest.fixture
def studio(bucket, tmp_path, monkeypatch):
    from sajha.core import storage_modules as sm
    import sajha.tools.impl as pkg
    pkg_dir, scripts = tmp_path / 'impl', tmp_path / 'scripts'
    pkg_dir.mkdir()
    scripts.mkdir()
    monkeypatch.setattr(sm, '_package_dir', lambda: pkg_dir)
    monkeypatch.setattr(sm, '_scripts_dir', lambda: scripts)
    before = list(pkg.__path__)
    yield sm, pkg_dir, scripts
    pkg.__path__[:] = before
    for name in [n for n in sys.modules if n.startswith('sajha.tools.impl.studio_zz')]:
        del sys.modules[name]


SRC = 'class ZzTool:\n    VALUE = {v}\n'


def test_publish_then_materialise_on_another_instance(studio, bucket):
    sm, pkg_dir, scripts = studio
    (pkg_dir / 'studio_zz_one.py').write_text(SRC.format(v=1))
    (scripts / 'zz_script.sh').write_text('echo hi\n')
    cfg = {'name': 'zz_one', 'implementation': 'sajha.tools.impl.studio_zz_one.ZzTool'}
    assert sm.publish_for_config(json.dumps(cfg)) == ['studio/modules/studio_zz_one.py']
    scfg = {'name': 'zz_script', 'script': {'script_type': 'bash', 'script_file': 'zz_script.sh'}}
    assert sm.publish_for_config(scfg) == ['config/scripts/zz_script.sh']
    assert sm.publish_for_config({'name': 'x', 'implementation': 'sajha.tools.impl.calculator_tool.Calc'}) == []

    # "another instance": nothing local
    (pkg_dir / 'studio_zz_one.py').unlink()
    (scripts / 'zz_script.sh').unlink()
    written = sm.materialise_for_config(cfg) + sm.materialise_for_config(scfg)
    cached = sm.cache_dir(bucket) / 'studio_zz_one.py'
    assert written == [str(cached), str(scripts / 'zz_script.sh')]
    import importlib
    assert importlib.import_module('sajha.tools.impl.studio_zz_one').ZzTool.VALUE == 1
    from sajha.sandbox.tools import SandboxedPythonTool
    assert SandboxedPythonTool._locate('sajha.tools.impl.studio_zz_one') == cached
    assert sm.materialise_for_config(cfg) == []              # fresh: nothing to do

    # an edit on another instance refreshes the copy and the imported module
    bucket.write_text('studio/modules/studio_zz_one.py', SRC.format(v=2))
    import os
    os.utime(cached, (0, 0))
    assert sm.materialise_for_config(cfg) == [str(cached)]
    assert sys.modules['sajha.tools.impl.studio_zz_one'].ZzTool.VALUE == 2


def test_only_generated_module_names_materialise(studio, bucket):
    sm, _, _ = studio
    bucket.write_text('studio/modules/calculator_tool.py', 'raise SystemExit\n')
    assert sm.materialise_for_config({'name': 'c', 'implementation': 'sajha.tools.impl.calculator_tool.C'}) == []
    assert sm.module_leaf({'name': 'c', 'implementation': 'sajha.tools.impl.studio_a.b.C'}) is None
    assert sm.script_file({'name': 'z', 'script': {'script_file': '../../etc/passwd'}}) is None


def test_local_backend_is_a_no_op(studio, monkeypatch, tmp_path):
    sm, pkg_dir, _ = studio
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path)))
    (pkg_dir / 'studio_zz_two.py').write_text(SRC.format(v=1))
    cfg = {'name': 'zz_two', 'implementation': 'sajha.tools.impl.studio_zz_two.ZzTool'}
    assert sm.publish_for_config(cfg) == [] and sm.materialise_for_config(cfg) == []


# ── plugins from a bucket ────────────────────────────────────────────────────

def test_plugins_are_mirrored_from_the_bucket(bucket, monkeypatch):
    from sajha.core.plugins import PluginManager

    class Reg:
        def __init__(self):
            self.tools = {}

        def register_tool_from_dict(self, cfg, source=None):
            self.tools[cfg['name']] = cfg

        def register_tool(self, tool):
            self.tools[tool.name] = tool

        def unregister_tool(self, name):
            self.tools.pop(name, None)

    bucket.write_text('config/plugins/demo/plugin.json', json.dumps({'name': 'demo', 'version': '1.0.0',
                                                                      'min_sajha_version': '0.0.0'}))
    bucket.write_text('config/plugins/demo/tools/one.json', json.dumps({'name': 'plug_one'}))
    stale = bucket.cache_dir / 'config/plugins/demo/tools/gone.json'
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text(json.dumps({'name': 'plug_gone'}))
    reg = Reg()
    pm = PluginManager(reg)
    pm.PLUGINS_DIR = 'config/plugins'
    assert [m.name for m in pm.discover()] == ['demo']
    assert not stale.exists()                               # removed from the bucket: gone from the mirror
    assert pm.load_plugin('demo').tools_registered == 1 and set(reg.tools) == {'plug_one'}


# ── workflow file triggers ───────────────────────────────────────────────────

def test_a_bucket_event_drops_the_file_trigger_poll_claim():
    from sajha.core.state.memory import MemoryStateStore
    from sajha.workflows.service import WorkflowService

    class Fake:
        state = MemoryStateStore()

        def _triggers(self, kind):
            yield {'name': 'wf'}, {'id': 'drop', 'prefix': 'inbox'}
            yield {'name': 'wf'}, {'id': 'other', 'prefix': 'elsewhere'}

    f = Fake()
    for t in ('drop', 'other'):
        f.state.add(f'wf:filepoll:wf:{t}', 'w1', ttl=600)
    WorkflowService.on_storage_paths(f, ['inbox/new.csv', 'data/x'])
    assert f.state.get('wf:filepoll:wf:drop') is None
    assert f.state.get('wf:filepoll:wf:other') == 'w1'


# ── guardrail: migrated subsystems keep no direct config IO ──────────────────

MIGRATED = ['sajha/tools/tools_registry.py', 'sajha/core/prompts_registry.py', 'sajha/web/guides.py',
            'sajha/federation/store.py', 'sajha/tools/tool_files.py', 'sajha/core/storage_modules.py',
            'sajha/ai/planners_engine/registry.py', 'sajha/reports/files.py']
_DIRECT = re.compile(r"""(open|os\.listdir|glob\.glob|Path)\(\s*f?['"](\./)?config/""")


@pytest.mark.parametrize('path', MIGRATED)
def test_migrated_subsystems_do_not_open_config_files_directly(path):
    text = (ROOT / path).read_text(encoding='utf-8')
    hits = [line.strip() for line in text.splitlines() if _DIRECT.search(line)]
    assert hits == [], f'{path} reads config/ directly; go through get_storage(): {hits}'
