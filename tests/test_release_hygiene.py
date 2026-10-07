"""Release hygiene (Roadmap N3, N4, N5): one rate limiter, the demo users file retired, the
test suite in CI, and the schema check reporting through System Notices."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def test_one_rate_limiter_policy_rules_only():
    import sajha.security as sec
    for gone in ('check_user_rate_limit', 'check_key_rate_limit', 'get_user_rate_remaining',
                 '_user_limiter', '_key_limiter'):
        assert not hasattr(sec, gone), gone


def test_default_policy_ships_a_commented_rate_limit_that_parses():
    from sajha.policy.model import parse_text
    text = (ROOT / 'config/policies/00-default.yaml').read_text(encoding='utf-8')
    assert parse_text(text, '00-default.yaml').rules == []          # shipped: no rules
    lines = []
    for line in text.splitlines():
        if line.startswith('# rules:') or line.startswith('#   '):
            lines.append(line[2:])
        elif line != 'rules: []':
            lines.append(line)
    rules = parse_text('\n'.join(lines), '00-default.yaml').rules
    assert {r.id: r.rate_limit.per for r in rules} == {'per-user-rate': ('user',), 'per-key-rate': ('api_key',)}


def test_users_json_is_the_administrators_file_not_the_old_demo():
    """The old demo users file and its legacy loader are gone; config/users.json is now the
    administrators' file (sajha/auth/users_file.py, owner decision): git-ignored, with an example."""
    from sajha.core import config
    assert not hasattr(config.Settings, 'config_users_path') and 'config_users_path' not in config.Settings.model_fields
    assert not (ROOT / 'sajha/db/seed.py').exists()   # legacy JSON imports removed with the module
    yml = yaml.safe_load((ROOT / 'config/application.yml').read_text(encoding='utf-8'))
    assert 'users' not in (yml.get('config') or {})
    assert yml['auth']['users_file']['path'] == 'config/users.json'
    assert 'config/users.json' in (ROOT / '.gitignore').read_text().splitlines()
    assert (ROOT / 'config/users.json.example').exists()


def test_ci_runs_the_full_suite():
    wf = yaml.safe_load((ROOT / '.github/workflows/tests.yml').read_text(encoding='utf-8'))
    on = wf.get('on') or wf.get(True)                 # YAML 1.1 reads a bare "on" as True
    assert set(on['push']['branches']) == {'develop', 'main'}
    steps = wf['jobs']['pytest']['steps']
    runs = ' '.join(s.get('run', '') for s in steps)
    assert 'python -m pytest -q -p no:randomly tests clientsdk/tests' in runs
    assert 'SAJHA_TEST_POSTGRES_URL' in wf['jobs']['pytest']['env']
    assert any(s.get('with', {}).get('cache') == 'pip' for s in steps)


def test_schema_check_raises_and_clears_the_notice(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sajha import notices
    from sajha.db import schema
    calls = []
    monkeypatch.setattr(notices, 'raise_notice', lambda nid, **kw: calls.append(('raise', nid, kw)))
    monkeypatch.setattr(notices, 'clear_notice', lambda nid, **kw: calls.append(('clear', nid, kw)))
    e = create_engine(f'sqlite:///{tmp_path / "n.db"}')
    schema.run_script(e, schema.schema_file('sqlite'))
    schema.check(e, 'warn')                                       # not at start-up: no notice
    assert calls == []
    schema.check(e, 'warn', notify=True)
    assert calls[-1][:2] == ('clear', 'db.schema')
    with e.begin() as c:
        c.exec_driver_sql('ALTER TABLE users DROP COLUMN must_change_password')
    schema.check(e, 'warn', notify=True)
    kind, nid, kw = calls[-1]
    assert (kind, nid, kw['severity'], kw['source']) == ('raise', 'db.schema', 'error', 'db')
    assert 'ALTER TABLE users ADD COLUMN must_change_password' in kw['detail']
