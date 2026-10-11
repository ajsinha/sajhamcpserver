# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Tool folders: config/tools/<name>.json or config/tools/<folder>/<name>.json, one level deep.

The registered tool set is the same whatever the folders; a name lives in one place only (two files
with one name load neither, with a critical notice, until one goes); deeper files are ignored with a
notice; edits, enable/disable, ownership and deletes touch the tool's own file; creators file new tools
in a folder and refuse a name that exists anywhere; the monitor sees new and moved files; the object-store
backend and the `python -m sajha.tools` CLI work the same way. Design: sajha/tools/tool_files.py.
"""

import io
import json
import shutil
import time
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

from tests.tool_config_files import ROOT, TOOLS, tool_file

SAMPLE = 'calc_percentage_change'          # a shipped tool that loads without network or keys


def _cfg(name: str) -> dict:
    cfg = json.loads(tool_file(SAMPLE).read_text(encoding='utf-8'))
    cfg['name'] = name
    return cfg


def _put(base: Path, rel: str, cfg: dict) -> Path:
    p = base / 'config' / 'tools' / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    return p


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A local storage backend rooted at tmp_path; the registry's own poller stays off."""
    import sajha.core.storage as storage
    from sajha.tools.tools_registry import ToolsRegistry
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path)))
    monkeypatch.setattr(ToolsRegistry, 'start_monitoring', lambda self: None)
    monkeypatch.setattr(ToolsRegistry, 'start_retrying', lambda self: None)
    return tmp_path


def _registry(base: Path):
    """A registry of its own (not the process singleton) over base/config/tools."""
    from sajha.tools.tools_registry import ToolsRegistry
    reg = object.__new__(ToolsRegistry)
    ToolsRegistry.__init__(reg, str(base / 'config' / 'tools'))
    return reg


def _open_notices(prefix: str):
    from sajha import notices
    return {n['id']: n for n in notices.list_notices(state='open', source='tools') if n['id'].startswith(prefix)}


# ── the migration changed nothing ───────────────────────────────────────

def test_the_migrated_tree_registers_exactly_what_the_flat_layout_did(tmp_path, monkeypatch):
    """Every shipped config moved into a folder unchanged: flattened back into one directory (the
    layout before the move), the registry registers the same names with the same configs."""
    import sajha.core.storage as storage
    from sajha.tools.tools_registry import ToolsRegistry
    monkeypatch.setattr(ToolsRegistry, 'start_monitoring', lambda self: None)
    files = sorted(TOOLS.glob('*.json')) + sorted(TOOLS.glob('*/*.json'))
    assert files and not list(TOOLS.glob('*/*/*.json'))
    assert len({f.name for f in files}) == len(files)            # one place per name
    flat, tree = tmp_path / 'flat', tmp_path / 'tree'
    (flat / 'config' / 'tools').mkdir(parents=True)
    for f in files:
        shutil.copyfile(f, flat / 'config' / 'tools' / f.name)
    shutil.copytree(TOOLS, tree / 'config' / 'tools')
    seen = {}
    for label, base in (('flat', flat), ('tree', tree)):
        monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(base)))
        reg = _registry(base)
        seen[label] = ({n: json.dumps(c, sort_keys=True) for n, c in reg.tool_configs.items()},
                       sorted(reg.tools), dict(reg.tool_errors))
    assert seen['flat'] == seen['tree']
    assert len(seen['tree'][1]) + len(reg.skipped_tools) == len(files)   # skipped: a "requires" module is missing
    assert not any(TOOLS.glob('*.json')), 'root leftovers: every shipped tool is in a folder'


# ── layout rules ─────────────────────────────────────────────────────────

def test_folder_names():
    from sajha.tools.tool_files import folder_problem, slug_folder
    for ok in ('', 'fmp', 'bank_of_canada', 'a1-b', 'x' * 32):
        assert folder_problem(ok, check_tools=False) is None, ok
    for bad in ('Fmp', '1fmp', '_fmp', 'f mp', 'a/b', 'a__b', 'x' * 33, 'fmp.json', '-a'):
        assert folder_problem(bad, check_tools=False), bad
    assert slug_folder('Market Data') == 'market_data' and slug_folder('REST API') == 'rest_api'
    assert slug_folder('') == '' and slug_folder('42') == ''


def test_a_folder_may_not_be_named_like_a_tool(store):
    from sajha.tools.tool_files import folder_problem
    _put(store, 'grp/zz_alpha.json', _cfg('zz_alpha'))
    assert 'name of a tool' in folder_problem('zz_alpha')
    assert folder_problem('grp') is None


def test_a_name_in_two_places_loads_neither_until_one_goes(store):
    from sajha.tools.tools_registry import ToolsRegistry
    _put(store, 'zz_dup.json', _cfg('zz_dup'))
    folder_copy = _put(store, 'grp/zz_dup.json', _cfg('zz_dup'))
    _put(store, 'grp/zz_ok.json', _cfg('zz_ok'))
    reg = _registry(store)
    assert 'zz_ok' in reg.tools and 'zz_dup' not in reg.tools and 'zz_dup' not in reg.tool_configs
    assert reg.tool_errors['zz_dup'].startswith('Duplicate tool name')
    n = _open_notices('tools.duplicate:')['tools.duplicate:zz_dup']
    assert n['severity'] == 'critical'
    assert 'config/tools/zz_dup.json' in n['detail'] and 'config/tools/grp/zz_dup.json' in n['detail']
    reg.reload_all_tools()                                    # every load says so again
    assert 'zz_dup' not in reg.tools
    folder_copy.unlink()                                      # one file left: it loads again
    reg._scan_once()
    assert 'zz_dup' in reg.tools and reg.tool_path('zz_dup') == 'config/tools/zz_dup.json'
    assert 'tools.duplicate:zz_dup' not in _open_notices('tools.duplicate:')
    assert 'zz_dup' not in reg.tool_errors


def test_two_folders_with_one_name_and_recovery_on_reload(store):
    _put(store, 'a/zz_twin.json', _cfg('zz_twin'))
    second = _put(store, 'b/zz_twin.json', _cfg('zz_twin'))
    reg = _registry(store)
    assert 'zz_twin' not in reg.tools and 'tools.duplicate:zz_twin' in _open_notices('tools.duplicate:')
    second.unlink()
    reg.reload_all_tools()
    assert 'zz_twin' in reg.tools and reg.tool_folder('zz_twin') == 'a'
    assert 'tools.duplicate:zz_twin' not in _open_notices('tools.duplicate:')


def test_a_new_duplicate_seen_by_the_monitor_unloads_the_tool(store):
    _put(store, 'a/zz_one.json', _cfg('zz_one'))
    reg = _registry(store)
    assert 'zz_one' in reg.tools
    _put(store, 'zz_one.json', _cfg('zz_one'))
    reg._scan_once()
    assert 'zz_one' not in reg.tools and 'tools.duplicate:zz_one' in _open_notices('tools.duplicate:')
    (store / 'config' / 'tools' / 'zz_one.json').unlink()
    reg._scan_once()
    assert 'zz_one' in reg.tools


def test_files_nested_deeper_than_one_folder_are_ignored_with_a_notice(store):
    _put(store, 'a/b/zz_deep.json', _cfg('zz_deep'))
    _put(store, 'a/zz_shallow.json', _cfg('zz_shallow'))
    reg = _registry(store)
    assert 'zz_deep' not in reg.tools and 'zz_shallow' in reg.tools
    n = _open_notices('tools.too_deep')['tools.too_deep']
    assert n['severity'] == 'warning' and 'config/tools/a/b/zz_deep.json' in n['detail']
    (store / 'config' / 'tools' / 'a' / 'b' / 'zz_deep.json').unlink()
    reg.reload_all_tools()
    assert 'tools.too_deep' not in _open_notices('tools.too_deep')


# ── a folder tool's own file, and nothing else ──────────────────────────

def test_edits_enable_disable_ownership_and_delete_touch_only_the_folder_file(store):
    from sajha.core.storage import write_tool_config
    from sajha.studio.ownership import stamp_file
    from sajha.tools.tool_files import delete_config
    f = _put(store, 'grp/zz_mine.json', _cfg('zz_mine'))
    root = store / 'config' / 'tools' / 'zz_mine.json'
    reg = _registry(store)
    assert reg.tool_path('zz_mine') == 'config/tools/grp/zz_mine.json' and reg.tool_folder('zz_mine') == 'grp'
    assert reg._config_rel('zz_mine') == reg._config_rel('zz_mine.json') == 'config/tools/grp/zz_mine.json'
    reg.disable_tool('zz_mine')
    assert json.loads(f.read_text())['enabled'] is False and not root.exists()
    reg.enable_tool('zz_mine')
    assert json.loads(f.read_text())['enabled'] is True and not root.exists()
    reg.tool_configs['zz_mine']['description'] = 'edited'
    reg._save_tool_config('zz_mine')
    assert json.loads(f.read_text())['description'] == 'edited' and not root.exists()
    assert stamp_file('zz_mine', 'someone', 'json')
    assert json.loads(f.read_text())['metadata']['created_by'] == 'someone' and not root.exists()
    cfg = json.loads(f.read_text())
    cfg['description'] = 'rewritten'
    assert write_tool_config('zz_mine.json', cfg) == 'config/tools/grp/zz_mine.json'      # an edit never moves
    assert write_tool_config(str(store / 'config' / 'tools' / 'zz_mine.json'), cfg, folder='other') == \
        'config/tools/grp/zz_mine.json'
    reg.load_tool_from_config('zz_mine.json')
    assert reg.tools['zz_mine'].description == 'rewritten'
    assert delete_config('zz_mine') and not f.exists() and not f.parent.exists()          # empty folder goes too


def test_new_tools_go_to_the_folder_asked_for_else_the_root(store):
    from sajha.core.storage import write_tool_config
    from sajha.tools.tool_files import name_taken, writing_into
    assert write_tool_config('zz_new_a.json', _cfg('zz_new_a')) == 'config/tools/zz_new_a.json'
    assert write_tool_config('zz_new_b.json', _cfg('zz_new_b'), folder='grp') == 'config/tools/grp/zz_new_b.json'
    with writing_into('gen'):                     # what Studio routes wrap a generator in
        assert write_tool_config('zz_new_c.json', _cfg('zz_new_c')) == 'config/tools/gen/zz_new_c.json'
    with pytest.raises(ValueError):
        with writing_into('Bad Folder'):
            pass
    assert name_taken('zz_new_b') == 'config/tools/grp/zz_new_b.json' and name_taken('zz_nope') is None


# ── the monitor ──────────────────────────────────────────────────────────

def test_the_monitor_sees_new_and_moved_files_in_folders(store):
    from sajha.tools.tool_files import move
    _put(store, 'zz_mover.json', _cfg('zz_mover'))
    reg = _registry(store)
    _put(store, 'grp/zz_fresh.json', _cfg('zz_fresh'))
    reg._scan_once()
    assert 'zz_fresh' in reg.tools and reg.tool_folder('zz_fresh') == 'grp'
    src = store / 'config' / 'tools' / 'zz_mover.json'
    dst = store / 'config' / 'tools' / 'grp' / 'zz_mover.json'
    src.rename(dst)                               # a move done outside SAJHA (mv, git mv)
    reg._scan_once()
    assert 'zz_mover' in reg.tools and reg.tool_path('zz_mover') == 'config/tools/grp/zz_mover.json'
    assert move(['zz_mover'], 'other') == [('zz_mover', 'config/tools/grp/zz_mover.json',
                                            'config/tools/other/zz_mover.json')]
    reg._scan_once()
    assert 'zz_mover' in reg.tools and reg.tool_folder('zz_mover') == 'other'
    assert 'tools.duplicate:zz_mover' not in _open_notices('tools.duplicate:')


def test_a_hot_reload_check_applies_folder_adds_changes_and_removals(store):
    """One hot-reload check (hot_reload.interval_seconds) applies every kind of change under config/tools."""
    from sajha.core.hot_reload_manager import ConfigReloader
    _put(store, 'grp/zz_watched.json', _cfg('zz_watched'))
    _put(store, 'grp/zz_watched_2.json', _cfg('zz_watched_2'))
    _put(store, 'zz_twin_hr.json', _cfg('zz_twin_hr'))
    twin = _put(store, 'other/zz_twin_hr.json', _cfg('zz_twin_hr'))
    reg = _registry(store)
    check = ConfigReloader(tools_registry=reg, reload_interval=3600).hot_reload._check_and_reload
    assert 'zz_twin_hr' not in reg.tools
    changed = _cfg('zz_watched')
    changed['description'] = 'changed in its folder'
    f = _put(store, 'grp/zz_watched.json', changed)
    t = time.time() + 5
    import os
    os.utime(f, (t, t))
    _put(store, 'newgrp/zz_new_folder_tool.json', _cfg('zz_new_folder_tool'))         # a new folder
    twin.unlink()                                                                       # the duplicate resolves
    check()
    assert reg.tools['zz_watched'].description == 'changed in its folder'
    assert 'zz_new_folder_tool' in reg.tools and 'zz_twin_hr' in reg.tools
    assert 'tools.duplicate:zz_twin_hr' not in _open_notices('tools.duplicate:')
    shutil.rmtree(store / 'config' / 'tools' / 'grp')                                   # a folder removed
    check()
    assert 'zz_watched' not in reg.tools and 'zz_watched_2' not in reg.tools
    assert not any(t['name'] in ('zz_watched', 'zz_watched_2') for t in reg.get_all_tools())


# ── retry of tools that failed to load ───────────────────────────────────

class _NeedsEnv:
    attempts = 0


def _needs_env_module(monkeypatch):
    """A tool class that fails to construct until ZZ_RETRY_KEY is set (as a missing API key would)."""
    import sys
    import types
    from sajha.tools.base_mcp_tool import BaseMCPTool
    import os

    class NeedsEnvTool(BaseMCPTool):
        def __init__(self, config):
            _NeedsEnv.attempts += 1
            if not os.environ.get('ZZ_RETRY_KEY'):
                raise RuntimeError('ZZ_RETRY_KEY is not set')
            super().__init__(config)

        def get_input_schema(self):
            return {'type': 'object', 'properties': {}}

        def get_output_schema(self):
            return {}

        def execute(self, arguments):
            return {'ok': True}

    mod = types.ModuleType('zz_retry_mod')
    mod.NeedsEnvTool = NeedsEnvTool
    monkeypatch.setitem(sys.modules, 'zz_retry_mod', mod)
    _NeedsEnv.attempts = 0
    return {'name': 'zz_needs_env', 'description': 'needs an env var', 'implementation': 'zz_retry_mod.NeedsEnvTool'}


def test_a_failed_tool_loads_once_its_env_var_is_set_without_touching_its_file(store, monkeypatch):
    monkeypatch.setenv('SAJHA_TOOLS_RETRY_FAILED_SECONDS', '60')
    monkeypatch.delenv('ZZ_RETRY_KEY', raising=False)
    _put(store, 'grp/zz_needs_env.json', _needs_env_module(monkeypatch))
    reg = _registry(store)
    assert 'zz_needs_env' not in reg.tools and 'ZZ_RETRY_KEY' in reg.tool_errors['zz_needs_env']
    t0 = 1000.0
    assert reg.retry_failed(now=t0) == [] and _NeedsEnv.attempts == 1          # noted; first retry at +60s
    assert reg.retry_failed(now=t0 + 59) == [] and _NeedsEnv.attempts == 1
    assert reg.retry_failed(now=t0 + 60) == [] and _NeedsEnv.attempts == 2     # failed again: next in 120s
    assert reg.retry_failed(now=t0 + 179) == [] and _NeedsEnv.attempts == 2
    assert reg.retry_failed(now=t0 + 180) == [] and _NeedsEnv.attempts == 3    # next in 240s
    assert reg._retry_state['zz_needs_env']['next'] == t0 + 180 + 240
    monkeypatch.setenv('ZZ_RETRY_KEY', 'now set')
    assert reg.retry_failed(now=t0 + 419) == []
    assert reg.retry_failed(now=t0 + 420) == ['zz_needs_env']
    assert 'zz_needs_env' in reg.tools and 'zz_needs_env' not in reg.tool_errors
    assert 'zz_needs_env' not in reg._retry_state


def test_retry_back_off_is_capped_and_duplicates_are_not_retried(store, monkeypatch):
    monkeypatch.setenv('SAJHA_TOOLS_RETRY_FAILED_SECONDS', '60')
    monkeypatch.delenv('ZZ_RETRY_KEY', raising=False)
    _put(store, 'zz_needs_env.json', _needs_env_module(monkeypatch))
    _put(store, 'a/zz_dup_retry.json', _cfg('zz_dup_retry'))
    _put(store, 'b/zz_dup_retry.json', _cfg('zz_dup_retry'))
    reg = _registry(store)
    t = 0.0
    reg.retry_failed(now=t)
    for _ in range(12):
        t = reg._retry_state['zz_needs_env']['next']
        reg.retry_failed(now=t)
    assert reg._retry_state['zz_needs_env']['next'] - t == reg.RETRY_CAP_SECONDS
    assert 'zz_dup_retry' not in reg._retry_state and 'zz_dup_retry' not in reg.tools


def test_retry_disabled_with_zero(store, monkeypatch):
    monkeypatch.setenv('SAJHA_TOOLS_RETRY_FAILED_SECONDS', '0')
    monkeypatch.setenv('ZZ_RETRY_KEY', 'set')
    _put(store, 'zz_needs_env.json', _needs_env_module(monkeypatch))
    reg = _registry(store)
    reg.tool_errors['zz_needs_env'] = 'failed earlier'
    reg.tools.pop('zz_needs_env', None)
    assert reg.retry_interval() == 0
    assert reg.retry_failed(now=0) == [] and reg.retry_failed(now=10 ** 9) == []
    assert 'zz_needs_env' not in reg.tools


# ── the object-store backend ─────────────────────────────────────────────

def _memory_backend(cache_dir):
    from sajha.core.storage import _ObjectStorageBackend

    class Memory(_ObjectStorageBackend):
        def __init__(self):
            super().__init__('', str(cache_dir))
            self.objs, self.times, self.clock = {}, {}, 0

        def _fetch_bytes(self, key):
            if key not in self.objs:
                raise FileNotFoundError(key)
            return self.objs[key]

        def _store_bytes(self, key, data):
            self.clock += 1
            self.objs[key], self.times[key] = data, float(self.clock)

        def _object_exists(self, key):
            return key in self.objs

        def _delete_object(self, key):
            return self.objs.pop(key, None) is not None

        def _list_keys(self, prefix):
            return [k for k in self.objs if k.startswith(prefix)]

        def _object_mtime(self, key):
            return self.times.get(key, 0.0)

    return Memory()


def test_folders_on_an_object_store(tmp_path, monkeypatch):
    import sajha.core.storage as storage
    from sajha.tools.tool_files import delete_config, move
    from sajha.tools.tools_registry import ToolsRegistry
    monkeypatch.setattr(ToolsRegistry, 'start_monitoring', lambda self: None)
    mem = _memory_backend(tmp_path / 'cache')
    monkeypatch.setattr(storage, '_storage', mem)
    mem.write_json('config/tools/grp/zz_cloud.json', _cfg('zz_cloud'))
    mem.write_json('config/tools/zz_rooted.json', _cfg('zz_rooted'))
    mem.write_json('config/tools/a/b/zz_cloud_deep.json', _cfg('zz_cloud_deep'))
    reg = _registry(tmp_path / 'nowhere')
    assert {'zz_cloud', 'zz_rooted'} <= set(reg.tools) and 'zz_cloud_deep' not in reg.tools
    reg.disable_tool('zz_cloud')
    assert json.loads(mem.objs['config/tools/grp/zz_cloud.json'])['enabled'] is False
    assert 'config/tools/zz_cloud.json' not in mem.objs
    move(['zz_rooted'], 'grp')
    assert 'config/tools/grp/zz_rooted.json' in mem.objs and 'config/tools/zz_rooted.json' not in mem.objs
    reg.reload_all_tools()
    assert reg.tool_folder('zz_rooted') == 'grp' and 'zz_rooted' in reg.tools
    assert delete_config('zz_cloud') and 'config/tools/grp/zz_cloud.json' not in mem.objs


# ── the command line ─────────────────────────────────────────────────────

def test_cli_folders_dry_run_move_and_collision(store):
    from sajha.tools.__main__ import cmd_folders, cmd_move
    _put(store, 'zz_cli_a.json', _cfg('zz_cli_a'))
    _put(store, 'zz_cli_b.json', _cfg('zz_cli_b'))
    out = io.StringIO()
    assert cmd_folders(out) == 0 and 'zz_*' in out.getvalue() and 'Root: 2 tool(s)' in out.getvalue()
    out = io.StringIO()
    assert cmd_move('zz_cli_*', 'cli', dry_run=True, out=out) == 0
    assert 'would move zz_cli_a: config/tools/zz_cli_a.json -> config/tools/cli/zz_cli_a.json' in out.getvalue()
    assert (store / 'config' / 'tools' / 'zz_cli_a.json').exists()                   # nothing moved
    _put(store, 'cli/zz_cli_b.json', _cfg('zz_cli_b_other'))                         # the target path is taken
    err = io.StringIO()
    with redirect_stderr(err):
        assert cmd_move('zz_cli_b', 'cli', dry_run=False, out=io.StringIO()) == 1
    assert 'already exists' in err.getvalue() and (store / 'config' / 'tools' / 'zz_cli_b.json').exists()
    out = io.StringIO()
    assert cmd_move('zz_cli_a', 'cli', dry_run=False, out=out) == 0
    assert (store / 'config' / 'tools' / 'cli' / 'zz_cli_a.json').exists()
    assert not (store / 'config' / 'tools' / 'zz_cli_a.json').exists()
    with redirect_stderr(io.StringIO()):
        assert cmd_move('zz_cli_a', 'Bad', dry_run=True, out=io.StringIO()) == 1


# ── the Tools page groups by folder ──────────────────────────────────────

def test_tool_domain():
    from sajha.routes.tools_routes import tool_domain

    class Reg:
        def tool_folder(self, name):
            return {'zz_in_fmp': 'fmp', 'zz_at_root': ''}.get(name)

    reg = Reg()
    assert tool_domain(reg, {'name': 'zz_in_fmp'}) == {'folder': 'fmp', 'domain': 'fmp', 'unfiled': False}
    assert tool_domain(reg, {'name': 'zz_at_root'}) == {'folder': '', 'domain': '', 'unfiled': True}
    assert tool_domain(reg, {'name': 'weather__get_forecast'})['domain'] == 'weather'          # a proxied server
    remote = {'name': 'n__i__t', '_meta': {'io.sajha/net': {'locality': 'remote'}}}
    assert tool_domain(reg, remote) == {'folder': None, 'domain': '', 'unfiled': False}
    remote['_meta']['io.sajha/net']['folder'] = 'fred'
    assert tool_domain(reg, remote)['domain'] == 'fred'


# ── Studio: Import JSON, a creator's folder field, names taken anywhere ──

@pytest.fixture(scope='module')
def admin():
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        r = c.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'})
        assert r.status_code == 200
        yield c, {'Authorization': f"Bearer {r.json()['token']}"}
        for name in ('zz_test_fold_json', 'zz_test_fold_cat', 'zz_test_fold_root', 'zz_test_fold_rest'):
            c.post('/admin/studio/delete', json={'tool_name': name}, headers={'Authorization': f"Bearer {r.json()['token']}"})
        for f in list(TOOLS.glob('*/zz_test_fold_*')) + list(TOOLS.glob('zz_test_fold_*')) + \
                list((ROOT / 'sajha' / 'tools' / 'impl').glob('*zz_test_fold_*')):
            f.unlink()
        for d in TOOLS.glob('zz_test_fold*'):
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()


def test_import_json_files_the_tool_where_asked(admin):
    c, h = admin
    from sajha.app import tools_registry
    cfg = dict(_cfg('zz_test_fold_json'), folder='zz_test_folder_a')
    pv = c.post('/admin/studio/json/preview', json={'text': json.dumps(cfg)}, headers=h).json()
    assert pv['success'] and pv['folder'] == 'zz_test_folder_a' and not pv['errors']
    assert pv['path'] == 'config/tools/zz_test_folder_a/zz_test_fold_json.json' and 'folder' not in pv['config']
    r = c.post('/admin/studio/json/deploy', json={'config': cfg}, headers=h).json()
    assert r['success'], r
    saved = TOOLS / 'zz_test_folder_a' / 'zz_test_fold_json.json'
    assert saved.exists() and 'folder' not in json.loads(saved.read_text())
    assert tools_registry.tool_folder('zz_test_fold_json') == 'zz_test_folder_a'
    assert 'zz_test_fold_json' in tools_registry.tools
    # the name is taken now, whatever folder is asked for
    again = c.post('/admin/studio/json/deploy', json={'config': cfg, 'folder': ''}, headers=h).json()
    assert not again['success'] and 'exists already' in again['error']
    # the Tools page groups it under its folder
    page = c.get('/tools', headers=h).text
    assert '"zz_test_folder_a"' in page and 'Unfiled' in page
    _studio_delete(c, h, 'zz_test_fold_json')          # leave config/tools as found (any test order)


def test_import_json_folder_from_category_or_the_root(admin):
    c, h = admin
    from sajha.app import tools_registry
    cfg = _cfg('zz_test_fold_cat')
    cfg['metadata'] = dict(cfg.get('metadata') or {}, category='ZZ Test Fold Category')
    pv = c.post('/admin/studio/json/preview', json={'config': cfg}, headers=h).json()
    assert pv['folder'] == 'zz_test_fold_category'
    assert c.post('/admin/studio/json/deploy', json={'config': cfg}, headers=h).json()['success']
    assert tools_registry.tool_folder('zz_test_fold_cat') == 'zz_test_fold_category'
    root = _cfg('zz_test_fold_root')
    root['metadata'] = dict(root.get('metadata') or {}, category='42')          # no valid folder: the root
    r = c.post('/admin/studio/json/deploy', json={'config': root}, headers=h).json()
    assert r['success'] and r['folder'] == '' and r['config_file'] == 'config/tools/zz_test_fold_root.json'
    bad = c.post('/admin/studio/json/deploy', json={'config': _cfg('zz_test_fold_x'), 'folder': 'Not OK'},
                 headers=h).json()
    assert not bad['success'] and 'folder name' in bad['error']
    _studio_delete(c, h, 'zz_test_fold_cat', 'zz_test_fold_root')   # no root leftovers for the migration test


def _studio_delete(c, h, *names):
    for name in names:
        assert c.post('/admin/studio/delete', json={'tool_name': name}, headers=h).json()['success'], name


def test_a_creator_honours_the_folder_and_refuses_names_taken_in_a_folder(admin):
    c, h = admin
    from sajha.app import tools_registry
    body = {'name': 'zz_test_fold_rest', 'endpoint': 'https://example.com/api', 'method': 'GET',
            'description': 'A REST tool filed in a folder', 'folder': 'zz_test_folder_b'}
    r = c.post('/admin/studio/rest/deploy', json=body, headers=h).json()
    assert r['success'], r
    assert tools_registry.tool_path('zz_test_fold_rest') == 'config/tools/zz_test_folder_b/zz_test_fold_rest.json'
    # the name is taken in a folder now: refused, naming the folder (self-contained, any test order)
    v = c.post('/admin/studio/validate-name', json={'tool_name': 'zz_test_fold_rest'}, headers=h).json()
    assert not v['valid'] and 'zz_test_folder_b' in v['error']
    d = c.post('/admin/studio/delete', json={'tool_name': 'zz_test_fold_rest'}, headers=h).json()
    assert d['success'] and not (TOOLS / 'zz_test_folder_b').exists()


# ── "requires": tools that need an optional module ───────────────────────

@pytest.fixture(autouse=True)
def _no_requires_notices_left():
    yield
    from sajha import notices
    for nid in _open_notices('tools.requires:'):
        notices.clear_notice(nid)


def test_a_tool_whose_required_module_is_missing_is_skipped_with_one_notice_per_module(store, monkeypatch):
    monkeypatch.setenv('SAJHA_TOOLS_RETRY_FAILED_SECONDS', '60')
    for n in ('zz_req_a', 'zz_req_b'):
        _put(store, f'zzopt/{n}.json', dict(_cfg(n), requires=['zz_optional_mod']))
    _put(store, 'zzopt/zz_req_c.json', dict(_cfg('zz_req_c'), requires=['zz_optional_mod', 'json']))
    _put(store, 'zz_req_ok.json', dict(_cfg('zz_req_ok'), requires=['json']))
    reg = _registry(store)
    assert 'zz_req_ok' in reg.tools                                     # an installed requirement loads
    for n in ('zz_req_a', 'zz_req_b', 'zz_req_c'):
        assert n not in reg.tools and n not in reg.tool_errors and n not in reg.tool_configs
        assert reg.skipped_tools[n] == ['zz_optional_mod']
    open_ = _open_notices('tools.requires:')
    assert list(open_) == ['tools.requires:zz_optional_mod']
    n = open_['tools.requires:zz_optional_mod']
    assert n['severity'] == 'info'
    assert n['title'] == 'zz_optional_mod is not installed: 3 zz_optional_mod tools are skipped'
    assert 'zz_req_a, zz_req_b, zz_req_c' in n['detail']
    assert reg.retry_failed(now=1000.0) == []                           # still missing: nothing loads
    assert not reg._retry_state                                         # skipped tools are not failed tools


def test_installing_the_required_module_loads_the_tools_on_the_retry_loop_and_clears_the_notice(store, monkeypatch, tmp_path):
    monkeypatch.setenv('SAJHA_TOOLS_RETRY_FAILED_SECONDS', '60')
    _put(store, 'zzopt/zz_req_late.json', dict(_cfg('zz_req_late'), requires=['zz_late_mod']))
    reg = _registry(store)
    assert 'zz_req_late' in reg.skipped_tools and 'tools.requires:zz_late_mod' in _open_notices('tools.requires:')
    t0 = 1000.0
    assert reg.retry_failed(now=t0) == []
    site = tmp_path / 'site'
    site.mkdir()
    (site / 'zz_late_mod.py').write_text('X = 1\n', encoding='utf-8')
    monkeypatch.syspath_prepend(str(site))                              # "pip install" while running
    assert reg.retry_failed(now=t0 + 30) == []                          # checked at most once per interval
    assert reg.retry_failed(now=t0 + 60) == ['zz_req_late']
    assert 'zz_req_late' in reg.tools and not reg.skipped_tools
    assert 'tools.requires:zz_late_mod' not in _open_notices('tools.requires:')


def test_deleting_a_skipped_tools_file_clears_its_notice(store, monkeypatch):
    p = _put(store, 'zzopt/zz_req_gone.json', dict(_cfg('zz_req_gone'), requires=['zz_gone_mod']))
    reg = _registry(store)
    assert 'tools.requires:zz_gone_mod' in _open_notices('tools.requires:')
    p.unlink()
    reg.rescan(deleted=['config/tools/zzopt/zz_req_gone.json'])
    assert not reg.skipped_tools and 'tools.requires:zz_gone_mod' not in _open_notices('tools.requires:')


def test_shipped_qlrisk_tools_are_skipped_without_qlrisk(store, monkeypatch):
    """The 18 shipped qlrisk configs declare requires qlrisk: without it they are skipped with one notice."""
    import sajha.tools.tools_registry as tr
    real = tr.missing_modules
    monkeypatch.setattr(tr, 'missing_modules', lambda mods: [m for m in mods if m == 'qlrisk'] + real([m for m in mods if m != 'qlrisk']))
    shutil.copytree(TOOLS / 'qlrisk', store / 'config' / 'tools' / 'qlrisk')
    reg = _registry(store)
    shipped = sorted(p.stem for p in (TOOLS / 'qlrisk').glob('*.json'))
    assert sorted(reg.skipped_tools) == shipped and not reg.tools and not reg.tool_errors
    n = _open_notices('tools.requires:')['tools.requires:qlrisk']
    assert n['severity'] == 'info' and n['title'] == f'qlrisk is not installed: {len(shipped)} qlrisk tools are skipped'
