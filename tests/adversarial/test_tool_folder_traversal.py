# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Adversarial QA Plan 3.7 (tool folders), P0: nothing outside the tools directory is ever loaded or
written through it.

* A symbolic link (file or folder) under config/tools that points outside it is not loaded; a link that
  stays inside (a Kubernetes ConfigMap mount's ``..data``) still is. Found by this suite and fixed in
  ``LocalStorageBackend.list_files`` (a linked file used to load from anywhere).
* A tool name with a path separator or a leading dot (``../../x``) never becomes a file path: Import JSON
  refuses it and nothing is written. Found by this suite and fixed in ``tool_files.name_path_problem``
  (Import JSON used to write ``config/tools/../../x.json``).
* Folder names with ``..``, absolute paths, separators or unusual Unicode are refused; a tools directory
  configured outside the storage base falls back to config/tools.
"""

import json
import os
from pathlib import Path

import pytest

from tests.test_tool_folders import _cfg, _put, _registry, store  # noqa: F401


def test_links_out_of_the_tools_directory_are_not_loaded(store, tmp_path_factory):  # noqa: F811
    outside = tmp_path_factory.mktemp('outside')
    (outside / 'sub').mkdir()
    (outside / 'stolen.json').write_text(json.dumps(_cfg('zz_adv_outside_file')))
    (outside / 'sub' / 'zz_adv_outside_dir.json').write_text(json.dumps(_cfg('zz_adv_outside_dir')))
    tools = store / 'config' / 'tools'
    _put(store, 'zz_adv_inside.json', _cfg('zz_adv_inside'))
    _put(store, 'real/zz_adv_target.json', _cfg('zz_adv_target'))
    os.symlink(outside / 'stolen.json', tools / 'zz_adv_link_out.json')
    os.symlink(outside / 'sub', tools / 'linked_out')
    os.symlink(outside, tools / 'linkroot')
    os.symlink(tools / 'real' / 'zz_adv_target.json', tools / 'zz_adv_link_in.json')
    os.symlink('/etc/hostname', tools / 'zz_adv_etc.json')
    reg = _registry(store)
    assert 'zz_adv_inside' in reg.tools
    for name in ('zz_adv_outside_file', 'zz_adv_outside_dir'):
        assert name not in reg.tools and name not in reg.tool_configs and name not in reg.tool_errors
    assert 'zz_adv_etc' not in reg.tool_errors and 'zz_adv_etc' not in reg.tools
    from sajha.core.storage import get_storage
    listed = get_storage().list_files('config/tools', '*.json')
    assert 'config/tools/zz_adv_link_in.json' in listed                    # a link inside still lists
    assert not any('link_out' in p or 'linked_out' in p or 'linkroot' in p or 'etc' in p for p in listed)


@pytest.mark.parametrize('bad', ['../../zz_adv_escape', '..\\..\\zz_adv_escape', '/tmp/zz_adv_escape',
                                 '.zz_adv_hidden', 'zz/adv', 'zz\x00adv'])
def test_a_tool_name_never_becomes_a_path(bad):
    from sajha.tools.tool_files import ToolFileIndex, name_path_problem
    assert name_path_problem(bad)
    with pytest.raises(ValueError):
        ToolFileIndex('config/tools').new_path(bad)


@pytest.fixture(scope='module')
def admin_bearer(web):
    c, _ = web
    from sajha.security import _login_throttle
    _login_throttle.reset()
    r = c.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'})
    assert r.status_code == 200
    return c, {'Authorization': f"Bearer {r.json()['token']}"}


@pytest.mark.parametrize('bad', ['../../zz_adv_escape', '../zz_adv_escape', '.zz_adv_hidden'])
def test_import_json_refuses_a_traversing_name_and_writes_nothing(admin_bearer, bad):
    c, h = admin_bearer
    root = Path.cwd()
    cfg = _cfg(bad)
    pv = c.post('/admin/studio/json/preview', json={'config': cfg}, headers=h)
    assert pv.status_code == 200 and pv.json()['errors'], pv.text
    assert '..' not in pv.json()['path']
    r = c.post('/admin/studio/json/deploy', json={'config': cfg}, headers=h).json()
    assert not r['success']
    for p in (root / 'zz_adv_escape.json', root.parent / 'zz_adv_escape.json', root / 'config' / 'zz_adv_escape.json',
              root / 'config' / 'tools' / '.zz_adv_hidden.json'):
        assert not p.exists(), p


@pytest.mark.parametrize('folder', ['..', '../x', 'a/b', 'a\\b', 'tools/..', 'ｆｕｌｌ', 'café', 'x' * 40,
                                    'Upper', '-lead', 'a__b'])
def test_hostile_folder_names_are_refused(folder):
    from sajha.tools.tool_files import clean_folder, folder_problem, writing_into
    assert folder_problem(clean_folder(folder), check_tools=False), folder
    with pytest.raises(ValueError):
        with writing_into(folder):
            pass


def test_a_folder_given_as_an_absolute_path_stays_under_the_tools_directory():
    from sajha.tools.tool_files import ToolFileIndex
    assert ToolFileIndex('config/tools').new_path('zz_adv', '/etc/') == 'config/tools/etc/zz_adv.json'


@pytest.mark.parametrize('configured,expected', [('../outside', 'config/tools'), ('..', 'config/tools'),
                                                 ('/etc', 'etc')])
def test_a_tools_directory_outside_the_storage_base_falls_back(monkeypatch, configured, expected):
    """A parent-relative directory falls back to config/tools; an absolute one is read relative to the
    storage base (never the absolute path)."""
    from sajha.tools import tool_files
    from sajha.tools.tools_registry import ToolsRegistry
    monkeypatch.setattr(ToolsRegistry, '_instance', None)
    monkeypatch.setenv('SAJHA_CONFIG_TOOLS_DIR', configured)
    assert tool_files.default_prefix() == expected
