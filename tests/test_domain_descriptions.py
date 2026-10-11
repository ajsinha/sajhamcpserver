# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Domain descriptions: an optional <tools dir>/<folder>/domain.txt appended to the served description of
every tool in the folder (tools/list in both eras, REST, Tools page, Ask SAJHA, SAJHA Net), never written
into a tool's JSON; longer than tools.domain_description_max_chars is refused with a notice, never cut; a
root domain.txt is ignored with a notice; the monitor reloads it; SAJHA Net leaves it out at its 1024
limit. Design: docs/architecture/Architecture.md §5 (sajha/tools/domain_text.py)."""

import json
import os
from pathlib import Path

import pytest

from tests.tool_config_files import tool_file

SAMPLE = 'calc_percentage_change'
DOMAIN = 'Zeta data: values in percent. Cite "Source: Zeta".'


def _cfg(name: str) -> dict:
    cfg = json.loads(tool_file(SAMPLE).read_text(encoding='utf-8'))
    cfg['name'] = name
    cfg['description'] = f'{name} does one thing.'
    return cfg


def _put(base: Path, rel: str, content) -> Path:
    p = base / 'config' / 'tools' / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content if isinstance(content, str) else json.dumps(content, indent=2), encoding='utf-8')
    return p


@pytest.fixture
def store(tmp_path, monkeypatch):
    import sajha.core.storage as storage
    from sajha.tools.tools_registry import ToolsRegistry
    monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(tmp_path)))
    monkeypatch.setattr(ToolsRegistry, 'start_monitoring', lambda self: None)
    monkeypatch.setattr(ToolsRegistry, 'start_retrying', lambda self: None)
    return tmp_path


def _registry(base: Path):
    from sajha.tools.tools_registry import ToolsRegistry
    reg = object.__new__(ToolsRegistry)
    ToolsRegistry.__init__(reg, str(base / 'config' / 'tools'))
    return reg


def _notices(prefix: str):
    from sajha import notices
    return {n['id']: n for n in notices.list_notices(state='open', source='tools') if n['id'].startswith(prefix)}


def _desc(reg, name):
    return reg.get_tool(name).to_mcp_format()['description']


def test_compose_and_first_sentence():
    from sajha.tools.domain_text import compose, first_sentence
    assert compose('Own.', 'Domain.') == 'Own.\n\nDomain.'
    assert compose('Own.\n', '') == 'Own.\n'
    assert compose('', 'Domain.') == 'Domain.'
    assert first_sentence('One. Two three.') == ('One.', 'Two three.')
    assert first_sentence('No stop') == ('No stop', '')


def test_folder_tools_are_served_with_the_domain_text_and_configs_keep_their_own(store):
    _put(store, 'zeta/zz_dom_a.json', _cfg('zz_dom_a'))
    _put(store, 'zeta/domain.txt', '\n' + DOMAIN + '\n\n')
    _put(store, 'other/zz_dom_b.json', _cfg('zz_dom_b'))
    _put(store, 'zz_dom_root.json', _cfg('zz_dom_root'))
    reg = _registry(store)
    a = reg.get_tool('zz_dom_a')
    assert a.to_mcp_format()['description'] == 'zz_dom_a does one thing.\n\n' + DOMAIN
    assert a.description == 'zz_dom_a does one thing.'                   # own description unchanged
    assert reg.tool_configs['zz_dom_a']['description'] == 'zz_dom_a does one thing.'
    assert _desc(reg, 'zz_dom_b') == 'zz_dom_b does one thing.'         # a folder without domain.txt
    assert _desc(reg, 'zz_dom_root') == 'zz_dom_root does one thing.'   # unfiled
    listed = {t['name']: t['description'] for t in reg.get_all_tools()}
    assert listed['zz_dom_a'].endswith(DOMAIN)
    assert reg.domain_description('zeta') == DOMAIN and reg.domain_description('other') == ''
    # the file on disk never gets the domain text, and saving the enabled flag keeps it out
    reg.disable_tool('zz_dom_a')
    reg.enable_tool('zz_dom_a')
    on_disk = json.loads((store / 'config/tools/zeta/zz_dom_a.json').read_text())
    assert on_disk['description'] == 'zz_dom_a does one thing.'
    # a tool built outside any registry has no domain
    standalone = type(a)(dict(reg.tool_configs['zz_dom_a']))
    assert standalone.to_mcp_format()['description'] == 'zz_dom_a does one thing.'


def test_too_long_is_refused_with_a_notice_not_truncated_and_root_is_ignored(store, monkeypatch):
    monkeypatch.setenv('SAJHA_TOOLS_DOMAIN_DESCRIPTION_MAX_CHARS', '40')
    _put(store, 'zeta/zz_dom_c.json', _cfg('zz_dom_c'))
    _put(store, 'zeta/domain.txt', 'x' * 41)
    _put(store, 'domain.txt', 'root text')
    reg = _registry(store)
    assert _desc(reg, 'zz_dom_c') == 'zz_dom_c does one thing.'
    refused = _notices('tools.domain_description:zeta')
    assert refused and refused['tools.domain_description:zeta']['severity'] == 'warning'
    assert '41 characters' in refused['tools.domain_description:zeta']['detail']
    root = _notices('tools.domain_description_root')
    assert root and root['tools.domain_description_root']['severity'] == 'info'
    # fixed: the notices clear on the next scan, and the text is served
    _put(store, 'zeta/domain.txt', 'Short.')
    os.remove(store / 'config/tools/domain.txt')
    reg._scan_domain_texts()
    assert _desc(reg, 'zz_dom_c').endswith('\n\nShort.')
    assert not _notices('tools.domain_description:zeta') and not _notices('tools.domain_description_root')


def test_hot_reload_add_edit_delete_announces_a_catalog_change(store):
    _put(store, 'zeta/zz_dom_d.json', _cfg('zz_dom_d'))
    reg = _registry(store)
    seen = []
    reg.add_change_listener(lambda: seen.append(1))
    assert _desc(reg, 'zz_dom_d') == 'zz_dom_d does one thing.'
    p = _put(store, 'zeta/domain.txt', 'First.')
    with reg.bulk():
        reg._scan_once()
    assert _desc(reg, 'zz_dom_d').endswith('\n\nFirst.') and seen
    n = len(seen)
    p.write_text('Second.', encoding='utf-8')
    os.utime(p, (p.stat().st_atime + 5, p.stat().st_mtime + 5))
    with reg.bulk():
        reg._scan_once()
    assert _desc(reg, 'zz_dom_d').endswith('\n\nSecond.') and len(seen) > n
    n = len(seen)
    p.unlink()
    with reg.bulk():
        reg._scan_once()
    assert _desc(reg, 'zz_dom_d') == 'zz_dom_d does one thing.' and len(seen) > n
    n = len(seen)
    with reg.bulk():
        reg._scan_once()                                  # nothing changed: nothing announced
    assert len(seen) == n


def test_ask_sajha_index_and_tool_definition_use_the_served_description(store):
    _put(store, 'zeta/zz_dom_e.json', _cfg('zz_dom_e'))
    _put(store, 'zeta/domain.txt', DOMAIN)
    reg = _registry(store)
    tool = reg.get_tool('zz_dom_e')
    from sajha.ai.intelligence import _tool_definition
    from sajha.ai.tool_resolver import _embedding_text
    d = _tool_definition('zz_dom_e', tool)
    text = json.dumps(d.to_dict(), default=str)
    assert 'Zeta data' in text
    assert 'Zeta data' in _embedding_text('zz_dom_e', tool.config, {}, tool)


def test_sajha_net_leaves_the_domain_text_out_past_its_limit(store, monkeypatch):
    own = 'Own words. ' * 10
    cfg = _cfg('zz_dom_f')
    cfg['description'] = own.strip()
    _put(store, 'zeta/zz_dom_f.json', cfg)
    _put(store, 'zeta/domain.txt', DOMAIN)
    reg = _registry(store)
    from sajha.net.integration import catalogs
    src = catalogs.NativeCatalog(registry=reg)
    monkeypatch.setattr(catalogs, '_description_limit', lambda: 10_000)
    d = {t['name']: t for t in src._own(reg)}['zz_dom_f']
    assert d['description'].endswith(DOMAIN)
    monkeypatch.setattr(catalogs, '_description_limit', lambda: len(own) + 5)
    d = {t['name']: t for t in src._own(reg)}['zz_dom_f']
    assert d['description'] == own.strip()                   # domain left out; own words never cut
    from sajha.tools.domain_text import export_description
    long_own = type('T', (), {'description': 'y' * 50})()
    assert export_description(long_own, 'y' * 50, 10) == 'y' * 50   # no domain text: left as it is


def test_proxied_tools_get_no_domain(store):
    _put(store, 'zeta/zz_dom_g.json', _cfg('zz_dom_g'))
    _put(store, 'zeta/domain.txt', DOMAIN)
    reg = _registry(store)
    tool = reg.get_tool('zz_dom_g')
    tool.namespaced_name = True
    from sajha.tools.domain_text import served_description
    assert served_description(tool) == 'zz_dom_g does one thing.'


def test_domains_page_card_and_config_page_show_it(store, monkeypatch):
    from fastapi.testclient import TestClient
    import sajha.app as app_mod
    from sajha.app import create_app
    import sajha.core.storage as storage
    with TestClient(create_app()) as c:
        r = c.post('/api/auth/login', json={'user_id': 'admin', 'password': 'admin123'})
        h = {'Authorization': f"Bearer {r.json()['token']}"}
        monkeypatch.setattr(storage, '_storage', storage.LocalStorageBackend(str(store)))   # after start-up
        _put(store, 'zeta/zz_dom_h.json', _cfg('zz_dom_h'))
        _put(store, 'zeta/domain.txt', 'Zeta first sentence. And the rest of it.')
        reg = _registry(store)
        monkeypatch.setattr(app_mod, 'tools_registry', reg)
        page = c.get('/tools/domains', headers=h).text
        assert 'Zeta first sentence.' in page and 'And the rest of it.' in page and '<details>' in page
        cfg_page = c.get('/tools/zz_dom_h/config', headers=h).text
        assert 'toolDomainText' in cfg_page and 'Zeta first sentence.' in cfg_page
        listed = c.get('/api/tools/list', headers=h).json()['tools']
        assert any(t['name'] == 'zz_dom_h' and t['description'].endswith('And the rest of it.') for t in listed)
        # the config editor saves only the tool's own description
        own = c.get('/api/admin/tools/zz_dom_h/config', headers=h).json()
        assert own['description'] == 'zz_dom_h does one thing.'
        own['description'] = 'Edited own text.'
        assert c.post('/api/admin/tools/zz_dom_h/config', headers=h, json=own).status_code == 200
        on_disk = json.loads((store / 'config/tools/zeta/zz_dom_h.json').read_text())
        assert on_disk['description'] == 'Edited own text.'
        assert reg.get_tool('zz_dom_h').to_mcp_format()['description'] == \
            'Edited own text.\n\nZeta first sentence. And the rest of it.'


def test_shipped_domain_files_fit_and_name_real_folders():
    from tests.tool_config_files import TOOLS
    from sajha.tools.domain_text import DEFAULT_MAX_CHARS
    files = sorted(TOOLS.glob('*/domain.txt'))
    assert files
    assert not (TOOLS / 'domain.txt').exists()
    for f in files:
        text = f.read_text(encoding='utf-8').strip()
        assert 0 < len(text) <= DEFAULT_MAX_CHARS, f
        assert list(f.parent.glob('*.json')), f'{f}: a domain description for a folder with no tools'


def test_lint_reports_description_length_past_the_net_limit(store, monkeypatch):
    cfg = _cfg('zz_dom_i')
    cfg['description'] = 'Own words. ' * 20
    _put(store, 'zeta/zz_dom_i.json', cfg)
    _put(store, 'zeta/domain.txt', DOMAIN)
    _put(store, 'zz_dom_j.json', cfg | {'name': 'zz_dom_j'})
    reg = _registry(store)
    from sajha.net.integration import catalogs
    from sajha.quality.lint import lint_registry
    monkeypatch.setattr(catalogs, '_description_limit', lambda: 100)
    found = {(f.tool, f.rule) for f in lint_registry(reg, 'zz_dom_*')}
    assert ('zz_dom_i', 'description-length') in found
    assert ('zz_dom_j', 'description-length') not in found      # no domain: the net's own check applies
    monkeypatch.setattr(catalogs, '_description_limit', lambda: 10_000)
    assert not any(f.rule == 'description-length' for f in lint_registry(reg, 'zz_dom_*'))
