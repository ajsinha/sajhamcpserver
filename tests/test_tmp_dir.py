# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""SAJHA's temporary folder (``app.tmp_dir``, sajha/core/paths.py): the default, the environment
override, validation, what start-up changes (``tempfile``, the children's environment), DuckDB's
spill folder and the start-up sweep of SAJHA's own leftovers."""
import os
import subprocess
import sys
import tempfile
import time

import pytest

from sajha.core import paths
from sajha.core.config import load_yaml_config


@pytest.fixture
def fresh(monkeypatch):
    """A process whose temp folder has not been applied; everything apply_tmp_dir changes is put back."""
    saved = tempfile.tempdir
    for k in ('TMPDIR', 'TEMP', 'TMP'):
        if k in os.environ:
            monkeypatch.setenv(k, os.environ[k])
        else:
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(paths, '_applied', None)
    yield monkeypatch
    tempfile.tempdir = saved


def test_the_shipped_default_is_the_system_temp_directory(fresh):
    assert load_yaml_config().get('app.tmp_dir') == ''           # application.yml: empty
    fresh.delenv(paths.ENV, raising=False)
    assert paths.configured_tmp_dir() == paths._SYSTEM_TMP
    if sys.platform.startswith('linux') and not os.environ.get('TMPDIR'):
        assert paths.configured_tmp_dir() == '/tmp'
    assert load_yaml_config().get('app.tmp_max_age_hours') == '24'


def test_the_environment_overrides_and_a_missing_folder_is_created_private(fresh, tmp_path):
    target = tmp_path / 'a' / 'sajha-tmp'
    fresh.setenv(paths.ENV, str(target))
    assert paths.configured_tmp_dir() == str(target)
    assert paths.tmp_dir() == str(target)
    assert target.is_dir() and (target.stat().st_mode & 0o777) == 0o700


def test_a_relative_value_is_made_absolute(fresh, tmp_path):
    fresh.chdir(tmp_path)
    fresh.setenv(paths.ENV, 'scratch-tmp')
    assert paths.configured_tmp_dir() == str(tmp_path / 'scratch-tmp')


def test_a_file_is_refused(fresh, tmp_path):
    f = tmp_path / 'not-a-dir'
    f.write_text('x')
    fresh.setenv(paths.ENV, str(f))
    with pytest.raises(paths.TmpDirError, match='app.tmp_dir.*not a directory'):
        paths.apply_tmp_dir()
    assert paths._applied is None


@pytest.mark.skipif(os.name != 'posix' or os.geteuid() == 0, reason='root writes anywhere')
def test_a_read_only_folder_is_refused(fresh, tmp_path):
    d = tmp_path / 'ro'
    d.mkdir()
    d.chmod(0o500)
    try:
        fresh.setenv(paths.ENV, str(d))
        with pytest.raises(paths.TmpDirError, match='not writable'):
            paths.validate_tmp_dir(str(d))
        fresh.setenv(paths.ENV, str(d / 'below'))
        with pytest.raises(paths.TmpDirError, match='cannot create'):
            paths.validate_tmp_dir(str(d / 'below'))
    finally:
        d.chmod(0o700)


def test_start_up_points_tempfile_and_children_at_it(fresh, tmp_path):
    target = tmp_path / 'sajha-tmp'
    fresh.setenv(paths.ENV, str(target))
    assert paths.apply_tmp_dir() == str(target)
    assert tempfile.gettempdir() == str(target)
    fd, name = tempfile.mkstemp()
    os.close(fd)
    assert os.path.dirname(name) == str(target)
    for k in ('TMPDIR', 'TEMP', 'TMP'):
        assert os.environ[k] == str(target)
    assert paths.child_tmp_env() == {'TMPDIR': str(target), 'TEMP': str(target), 'TMP': str(target)}
    out = subprocess.run([sys.executable, '-c', 'import tempfile; print(tempfile.gettempdir())'],
                         capture_output=True, text=True, timeout=30).stdout.strip()
    assert out == str(target)                                     # a child process inherits it


def test_the_sandbox_launcher_carries_it(fresh, tmp_path):
    # (a stdio upstream: tests/test_federation_container.py)
    target = tmp_path / 'sajha-tmp'
    fresh.setenv(paths.ENV, str(target))
    paths.apply_tmp_dir()
    from sajha.sandbox.backends import Sandbox
    env = Sandbox.launch_env(object.__new__(Sandbox))
    assert env['TMPDIR'] == env['TEMP'] == env['TMP'] == str(target)


def test_the_app_refuses_to_start_with_an_unusable_folder(fresh, tmp_path):
    f = tmp_path / 'file'
    f.write_text('x')
    fresh.setenv(paths.ENV, str(f))
    from sajha.app import SajhaMCPServerWebApp
    with pytest.raises(paths.TmpDirError):
        SajhaMCPServerWebApp()


def test_a_command_refuses_an_unusable_folder(tmp_path):
    f = tmp_path / 'file'
    f.write_text('x')
    env = dict(os.environ, SAJHA_APP_TMP_DIR=str(f))
    r = subprocess.run([sys.executable, '-m', 'sajha.auth', 'rehash'], capture_output=True, text=True,
                       timeout=60, env=env)
    assert r.returncode == 2 and 'app.tmp_dir' in r.stderr and 'not a directory' in r.stderr


# ── the sweep ────────────────────────────────────────────────────

def _age(path, hours):
    t = time.time() - hours * 3600
    for root, dirs, files in os.walk(path) if os.path.isdir(path) else [(None, [], [])]:
        for n in dirs + files:
            os.utime(os.path.join(root, n), (t, t), follow_symlinks=False)
    os.utime(path, (t, t), follow_symlinks=False)


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, '-c', 'pass'])
    p.wait()
    return p.pid


def test_the_sweep_removes_only_old_sajha_leftovers(fresh, tmp_path):
    d = tmp_path / 'tmp'
    d.mkdir()
    old_file = d / 'sajha-rag-abc.db'
    old_dir = d / 'sajha-sbx-1234'
    (old_dir / 'inner').mkdir(parents=True)
    (old_dir / 'inner' / 'f').write_text('x')
    fresh_file = d / 'sajha-rag-new.db'
    foreign = d / 'other-old.db'
    cache = d / 'sajha-cache'
    cache.mkdir()
    live = d / f'sajha-duckdb-p{os.getpid()}-1'
    live.mkdir()
    dead = d / f'sajha-duckdb-p{_dead_pid()}-1'
    dead.mkdir()
    mine = d / 'sajha-registered.db'
    touched_inside = d / 'sajha-sbx-recent'
    touched_inside.mkdir()
    (touched_inside / 'f').write_text('x')
    for p in (old_file, fresh_file, foreign, mine):
        p.write_text('x')
    for p in (old_file, old_dir, foreign, cache, live, dead, mine, touched_inside):
        _age(str(p), 48)
    os.utime(touched_inside / 'f')                         # something inside is recent: in use
    paths.register_tmp(str(mine))
    try:
        assert paths.sweep_tmp(max_age=0, folder=str(d)) == []          # 0: the sweep is off
        removed = paths.sweep_tmp(max_age=24, folder=str(d))
    finally:
        paths.unregister_tmp(str(mine))
    assert sorted(os.path.basename(p) for p in removed) == sorted([old_file.name, old_dir.name, dead.name])
    for p in (fresh_file, foreign, cache, live, mine, touched_inside):
        assert p.exists(), p
    for p in (old_file, old_dir, dead):
        assert not p.exists(), p


def test_start_up_sweeps_with_the_configured_age(fresh, tmp_path):
    d = tmp_path / 'tmp'
    d.mkdir()
    a = d / 'sajha-x-old'
    a.write_text('x')
    _age(str(a), 3)
    fresh.setenv(paths.ENV, str(d))
    fresh.setenv('SAJHA_APP_TMP_MAX_AGE_HOURS', '2')
    paths.apply_tmp_dir(sweep=True)
    assert not a.exists()


def test_registered_entries_go_at_exit(tmp_path):
    f = tmp_path / 'sajha-x.db'
    f.write_text('x')
    (tmp_path / 'sajha-x.db-wal').write_text('x')
    paths.register_tmp(str(f))
    paths._cleanup_registered()
    assert not f.exists() and not (tmp_path / 'sajha-x.db-wal').exists()


# ── DuckDB ───────────────────────────────────────────────────────

def test_duckdb_spills_under_the_folder_and_keeps_its_lockdown(fresh, tmp_path):
    pytest.importorskip('duckdb')
    target = tmp_path / 'sajha-tmp'
    fresh.setenv(paths.ENV, str(target))
    con = paths.duckdb_connect(config={'enable_external_access': False, 'lock_configuration': True})
    try:
        temp = con.execute("SELECT current_setting('temp_directory')").fetchone()[0]
        assert os.path.dirname(temp) == str(target)
        assert os.path.basename(temp).startswith(f'sajha-duckdb-p{os.getpid()}-')
        assert con.execute("SELECT current_setting('enable_external_access')").fetchone()[0] is False
        with pytest.raises(Exception):
            con.execute('SET enable_external_access = true')
    finally:
        con.close()
    other = paths.duckdb_connect()
    try:
        assert other.execute("SELECT current_setting('temp_directory')").fetchone()[0] != temp   # one each
    finally:
        other.close()
