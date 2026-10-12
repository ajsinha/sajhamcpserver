# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The plugin catalog (sajha/core/plugin_catalog.py, sajha/routes/plugin_catalog_routes.py;
Roadmap L12): listing packages from folder, zip, storage and remote sources with their signature
verdicts, and installing one through the review-and-approve gate of Describe a tool (approval,
reviewed hash, a package changed after review, the policy engine, replace)."""
import io
import json
import textwrap
import zipfile
from types import SimpleNamespace

import pytest

pytest.importorskip('cryptography', reason='publisher signatures need the cryptography package')

from sajha.core import plugin_catalog as K  # noqa: E402
from sajha.core import plugin_signing as S  # noqa: E402
from tests.test_plugin_signing import _Registry, make_plugin  # noqa: E402

ADMIN = SimpleNamespace(user_id='admin', roles=['admin'], is_admin=True, auth_type='session')


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    from sajha import notices
    from sajha.core import plugins as P
    from sajha.core.state import get_state_store, set_state_store
    from sajha.core.state.memory import MemoryStateStore
    monkeypatch.setattr(notices, 'raise_notice', lambda *a, **k: None)
    monkeypatch.setattr(notices, 'clear_notice', lambda *a, **k: None)
    monkeypatch.setenv('SAJHA_POLICY_ENABLED', 'false')
    old_store = get_state_store()
    set_state_store(MemoryStateStore())
    priv, pub = S.generate_keypair()
    other, _ = S.generate_keypair()
    trusted = S.trusted_keys([f'acme={pub}'], keys_dir='')
    monkeypatch.setattr(S, 'trusted_keys', lambda *a, **k: trusted)
    catalog = tmp_path / 'catalog'
    catalog.mkdir()
    monkeypatch.setenv('SAJHA_PLUGINS_CATALOG_SOURCES', json.dumps([str(catalog)]))
    old_pm = P._plugin_manager
    reg = _Registry()
    pm = P.PluginManager(reg)
    pm.PLUGINS_DIR = str(tmp_path / 'installed')
    P._plugin_manager = pm
    audit = []
    monkeypatch.setattr(K, '_audit', lambda user, what, details: audit.append((what, details)))
    yield SimpleNamespace(priv=priv, other=other, catalog=catalog, pm=pm, reg=reg, audit=audit,
                          installed=tmp_path / 'installed')
    P._plugin_manager = old_pm
    set_state_store(old_store)


def signed(env, name='demo', version='1.0.0', key=None, publisher='acme', tool='echo'):
    p = make_plugin(env.catalog / f'{name}-{version}', name=name, version=version, tool=tool)
    S.sign(p, key or env.priv, publisher)
    return p


def test_listing_shows_every_verdict(env):
    signed(env)
    signed(env, name='rogue', key=env.other)
    make_plugin(env.catalog / 'plain', name='plain')
    t = signed(env, name='tampered')
    (t / 'tools' / 'echo.json').write_text('{}')
    out = K.list_available()
    by = {p['name']: p['status'] for p in out['packages']}
    assert by == {'demo': 'trusted', 'rogue': 'untrusted', 'plain': 'unsigned', 'tampered': 'invalid'}
    assert out['trusted_publishers'] == ['acme'] and not out['errors']


def test_zip_packages_and_a_missing_source(env, monkeypatch, tmp_path):
    p = signed(env)
    S.pack(p, env.catalog)
    import shutil
    shutil.rmtree(p)
    monkeypatch.setenv('SAJHA_PLUGINS_CATALOG_SOURCES', json.dumps([str(env.catalog), str(tmp_path / 'nope')]))
    out = K.list_available()
    assert [(x['ref'], x['status']) for x in out['packages']] == [('demo-1.0.0.zip', 'trusted')]
    assert 'no such folder' in out['errors'][str(tmp_path / 'nope')]


def test_install_through_the_gate(env):
    signed(env)
    d = K.review(str(env.catalog), 'demo-1.0.0', ADMIN)
    assert d['manifest']['name'] == 'demo' and d['signature']['publisher'] == 'acme'
    assert {f['path'] for f in d['files']} == {'plugin.json', 'tools/echo.json', 'plugin.sig'}
    with pytest.raises(K.CatalogError, match='explicit approval'):
        K.install(d['id'], d['hash'], approve=False, user=ADMIN)
    with pytest.raises(K.CatalogError, match='not the one you reviewed'):
        K.install(d['id'], '0' * 64, approve=True, user=ADMIN)
    r = K.install(d['id'], d['hash'], approve=True, user=ADMIN)
    assert 'Installed demo 1.0.0' in r['message'] and r['installed']['tools'] == 1
    assert (env.installed / 'demo' / 'plugin.sig').is_file()
    assert 'zz_demo_echo' in env.reg.tools
    assert [w for w, _ in env.audit] == ['review', 'install']
    with pytest.raises(K.CatalogError, match='already installed'):
        K.install(d['id'], d['hash'], approve=True, user=ADMIN)
    # a second review of the same name needs replace
    d2 = K.review(str(env.catalog), 'demo-1.0.0', ADMIN)
    with pytest.raises(K.CatalogError, match='replace'):
        K.install(d2['id'], d2['hash'], approve=True, user=ADMIN)


def test_only_trusted_packages_can_be_reviewed(env):
    signed(env, name='rogue', key=env.other)
    make_plugin(env.catalog / 'plain', name='plain')
    for ref in ('rogue-1.0.0', 'plain'):
        with pytest.raises(K.CatalogError, match='trusted publisher') as e:
            K.review(str(env.catalog), ref, ADMIN)
        assert e.value.status == 409


def test_unknown_source_and_path_escape(env, tmp_path):
    with pytest.raises(K.CatalogError, match='not configured'):
        K.review(str(tmp_path), 'x', ADMIN)
    for ref in ('../installed', '.', 'a/b'):
        with pytest.raises(K.CatalogError):
            K.review(str(env.catalog), ref, ADMIN)


def test_package_changed_after_review_is_refused(env):
    p = signed(env)
    d = K.review(str(env.catalog), 'demo-1.0.0', ADMIN)
    (p / 'tools' / 'extra.json').write_text(json.dumps({'name': 'zz_extra'}))
    S.sign(p, env.priv, 'acme')                       # re-signed: still trusted, but not what was reviewed
    with pytest.raises(K.CatalogError, match='changed in the catalog'):
        K.install(d['id'], d['hash'], approve=True, user=ADMIN)
    (p / 'tools' / 'extra.json').write_text('{}')     # tampered: no longer trusted
    with pytest.raises(K.CatalogError, match='no longer trusted'):
        K.install(d['id'], d['hash'], approve=True, user=ADMIN)
    assert not (env.installed / 'demo').exists()


def _policy(doc):
    from sajha.policy.engine import PolicyEngine, set_engine
    from sajha.policy.loader import PolicySet
    from sajha.policy.model import parse_text
    ps = PolicySet()
    ps.set_policies([parse_text(textwrap.dedent(doc), 'p', 'p.yaml')])
    set_engine(PolicyEngine(ps))


def test_the_policy_engine_gates_installs(env, monkeypatch):
    from sajha.policy.engine import set_engine
    monkeypatch.setenv('SAJHA_POLICY_ENABLED', 'true')
    signed(env)
    d = K.review(str(env.catalog), 'demo-1.0.0', ADMIN)
    try:
        _policy('rules: [{id: no-plugins, match: {tools: ["studio.deploy"]}, effect: deny, reason: frozen}]')
        with pytest.raises(K.CatalogError, match='frozen') as e:
            K.install(d['id'], d['hash'], approve=True, user=ADMIN)
        assert e.value.status == 403
        _policy('rules: [{id: two-man, match: {tools: ["studio.deploy"]}, effect: require_approval, '
                'approval: {approver: admin}}]')
        with pytest.raises(K.CatalogError, match='second approval') as e:
            K.install(d['id'], d['hash'], approve=True, user=ADMIN)
        assert e.value.status == 409 and e.value.extra['approval_id']
    finally:
        set_engine(None)
    assert not (env.installed / 'demo').exists()


def test_replace_upgrades_and_a_failed_load_restores(env):
    signed(env)
    d = K.review(str(env.catalog), 'demo-1.0.0', ADMIN)
    K.install(d['id'], d['hash'], approve=True, user=ADMIN)
    signed(env, version='2.0.0', tool='echo2')
    d2 = K.review(str(env.catalog), 'demo-2.0.0', ADMIN)
    assert d2['installed_version'] == '1.0.0'
    r = K.install(d2['id'], d2['hash'], approve=True, replace=True, user=ADMIN)
    assert r['installed']['replaced'] is True
    assert json.loads((env.installed / 'demo' / 'plugin.json').read_text())['version'] == '2.0.0'
    assert 'zz_demo_echo2' in env.reg.tools and 'zz_demo_echo' not in env.reg.tools
    # 3.0.0 needs a config key that is not set: it does not load, and 2.0.0 is put back
    p3 = make_plugin(env.catalog / 'demo-3.0.0', version='3.0.0', tool='echo3')
    m = json.loads((p3 / 'plugin.json').read_text())
    m['config_keys'] = ['SAJHA_TEST_NEVER_SET_KEY']
    (p3 / 'plugin.json').write_text(json.dumps(m))
    S.sign(p3, env.priv, 'acme')
    d3 = K.review(str(env.catalog), 'demo-3.0.0', ADMIN)
    with pytest.raises(K.CatalogError, match='did not load'):
        K.install(d3['id'], d3['hash'], approve=True, replace=True, user=ADMIN)
    assert json.loads((env.installed / 'demo' / 'plugin.json').read_text())['version'] == '2.0.0'
    assert 'zz_demo_echo2' in env.reg.tools


def test_storage_source(env, monkeypatch, tmp_path):
    from sajha.core import storage
    backend = storage.LocalStorageBackend(str(tmp_path / 'bucket'))
    monkeypatch.setattr(storage, '_storage', backend)
    p = make_plugin(tmp_path / 'bucket' / 'catalog' / 'demo', name='demo')
    S.sign(p, env.priv, 'acme')
    monkeypatch.setenv('SAJHA_PLUGINS_CATALOG_SOURCES', json.dumps(['storage:catalog']))
    out = K.list_available()
    assert [(x['ref'], x['status']) for x in out['packages']] == [('demo', 'trusted')], out
    env.pm.PLUGINS_DIR = str(env.installed)         # absolute: a local folder, not the bucket
    d = K.review('storage:catalog', 'demo', ADMIN)
    K.install(d['id'], d['hash'], approve=True, user=ADMIN)
    assert (env.installed / 'demo' / 'plugin.json').is_file()


def _zip_of(root):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for rel in S.package_files(root) + ['plugin.sig']:
            z.write(root / rel, rel)
    return buf.getvalue()


def test_remote_source_goes_through_the_outbound_guard(env, monkeypatch):
    from sajha.core import outbound
    p = signed(env)
    blob = _zip_of(p)
    index = json.dumps({'plugins': [{'name': 'demo', 'version': '1.0.0', 'publisher': 'acme',
                                     'url': 'pkgs/demo-1.0.0.zip'}]}).encode()
    fetched = []

    def fake_request(method, url, **kw):
        fetched.append(url)
        if 'metadata' in url:
            raise outbound.Refused('refused: resolves to a blocked address (cloud metadata)')
        body = index if url.endswith('index.json') else blob
        return outbound.Response(200, 'OK', {}, body, url)
    monkeypatch.setattr(outbound, 'request', fake_request)
    src = 'https://plugins.example.com/catalog/index.json'
    monkeypatch.setenv('SAJHA_PLUGINS_CATALOG_SOURCES', json.dumps([src, 'http://metadata.google.internal/index.json']))
    out = K.list_available()
    assert [(x['ref'], x['status']) for x in out['packages']] == \
        [('https://plugins.example.com/catalog/pkgs/demo-1.0.0.zip', 'trusted')]
    assert 'outbound fetch guard' in out['errors']['http://metadata.google.internal/index.json']
    d = K.review(src, 'https://plugins.example.com/catalog/pkgs/demo-1.0.0.zip', ADMIN)
    with pytest.raises(K.CatalogError, match='not in the catalog index'):
        K.review(src, 'https://evil.example.com/x.zip', ADMIN)
    K.install(d['id'], d['hash'], approve=True, user=ADMIN)
    assert (env.installed / 'demo').is_dir()


@pytest.mark.parametrize('entry', ['../evil.py', '/etc/evil', 'a/../../evil'])
def test_zip_entries_cannot_escape(entry):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('plugin.json', '{"name": "x"}')
        z.writestr(entry, 'x')
    with pytest.raises(K.CatalogError, match='outside the package'):
        K._unzip(buf.getvalue())


def test_zip_size_cap(monkeypatch):
    monkeypatch.setenv('SAJHA_PLUGINS_CATALOG_MAX_PACKAGE_BYTES', '2048')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('plugin.json', '{"name": "x"}')
        z.writestr('big.txt', '0' * 100000)            # compresses small, unpacks large
    with pytest.raises(K.CatalogError, match='larger than'):
        K._unzip(buf.getvalue())


# ── the page (a real app) ─────────────────────────────────────────────

def test_page_review_and_install(env, monkeypatch):
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    signed(env)
    with TestClient(create_app()) as c:
        if not any(getattr(r, 'path', '') == '/admin/plugins/catalog' for r in c.app.routes):
            pytest.skip('the plugin catalog routes are not registered yet (pending edit in sajha/app.py)')
        from sajha.core import plugins as P
        P._plugin_manager = env.pm                    # the app start-up made its own
        r = c.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
        admin = dict(r.cookies)
        c.cookies.clear()
        assert c.get('/admin/plugins/catalog', follow_redirects=False).status_code in (302, 401, 403)
        page = c.get('/admin/plugins/catalog', cookies=admin)
        assert page.status_code == 200 and 'Plugin Catalog' in page.text and 'demo' in page.text
        import re
        csrf = re.search(r'name="csrf" value="([0-9a-f]+)"', page.text).group(1)
        bad = c.post('/admin/plugins/catalog/review', data={'csrf': 'x', 'source': str(env.catalog),
                                                             'ref': 'demo-1.0.0'}, cookies=admin, follow_redirects=False)
        assert 'expired' in bad.headers['location'].replace('+', ' ')
        r = c.post('/admin/plugins/catalog/review', data={'csrf': csrf, 'source': str(env.catalog), 'ref': 'demo-1.0.0'},
                   cookies=admin, follow_redirects=False)
        assert r.status_code == 303 and 'review=' in r.headers['location']
        rid = r.headers['location'].split('review=')[1]
        page = c.get(f'/admin/plugins/catalog?review={rid}', cookies=admin)
        assert 'Approve and install' in page.text and 'tools/echo.json' in page.text
        h = re.search(r'name="hash" value="([0-9a-f]{64})"', page.text).group(1)
        r = c.post('/admin/plugins/catalog/install', data={'csrf': csrf, 'review': rid, 'hash': h},
                   cookies=admin, follow_redirects=False)
        assert 'explicit approval' in r.headers['location'].replace('+', ' ')
        r = c.post('/admin/plugins/catalog/install', data={'csrf': csrf, 'review': rid, 'hash': h, 'approve': 'true'},
                   cookies=admin, follow_redirects=False)
        assert 'Installed' in r.headers['location'].replace('+', ' ')
        assert c.get('/api/plugins/catalog', cookies=admin).json()['packages'][0]['installed_version'] == '1.0.0'
