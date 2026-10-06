"""
Python Playground (/playground): the page renders for a signed-in user only; only the
playground (page and worker) carries the cross-origin isolation headers and the
WebAssembly-capable CSP; playground.* settings are validated; switching it off answers a
friendly 404 and hides the menu entry; missing vendored assets show an administrator hint;
the sajha bridge module is served, and works against the real API when run with a stand-in
for the browser's XMLHttpRequest.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

import pytest

from sajha.web import playground as pg

ROOT = Path(__file__).resolve().parent.parent


def _get(c, url, cookies=None, **kw):
    c.cookies.clear()
    return c.get(url, cookies=cookies, **kw)


def _pg_data(html):
    m = re.search(r'<script type="application/json" id="pgData">(.*?)</script>', html, re.S)
    assert m, 'pgData missing'
    return json.loads(m.group(1))


@pytest.fixture
def vendored(tmp_path, monkeypatch):
    """A fake vendored release, so the tests do not depend on scripts/fetch_pyodide.py having run."""
    d = tmp_path / pg.DEFAULT_PYODIDE_VERSION
    d.mkdir()
    for f in ('pyodide.mjs', 'pyodide.asm.wasm'):
        (d / f).write_text('x')
    (d / 'sajha-manifest.json').write_text(json.dumps({'version': pg.DEFAULT_PYODIDE_VERSION,
                                                       'packages': ['numpy', 'pandas']}))
    monkeypatch.setattr(pg, 'VENDOR_DIR', tmp_path)
    for k in ('ENABLED', 'ASSETS', 'PYODIDE_VERSION', 'ALLOW_PYPI'):
        monkeypatch.delenv(f'SAJHA_PLAYGROUND_{k}', raising=False)
    return d


# ── the page ────────────────────────────────────────────────────────────────

def test_playground_renders_for_a_signed_in_user(web, vendored):
    c, admin = web
    r = _get(c, '/playground', cookies=admin)
    assert r.status_code == 200
    t = r.text
    for needle in ('id="pgCells"', 'id="pgRunAll"', 'id="pgStop"', 'id="pgReset"', 'id="pgExamples"',
                   'id="pgSave"', 'id="pgLoad"', 'id="pgDownload"', 'id="pgUpload"', 'id="pgPackages"',
                   'vendor/codemirror/codemirror-python.min.js', 'js/playground.js', 'aria-live="polite"'):
        assert needle in t, needle
    data = _pg_data(t)
    assert data['assetsOk'] is True and data['assets'] == 'vendored'
    assert data['indexURL'] == f'/static/vendor/pyodide/{pg.DEFAULT_PYODIDE_VERSION}/'
    assert data['vendoredPackages'] == ['numpy', 'pandas']
    ids = [e['id'] for e in data['examples']]
    for want in ('numpy', 'pandas', 'matplotlib', 'scipy', 'sklearn', 'sajha_calc', 'sajha_ask'):
        assert want in ids
    assert 'id="pgAssetsHint"' not in t
    assert 'class="page-help"' in t and 'Python Playground' in t       # About this page


def test_playground_refuses_anonymous_callers(web):
    c, _ = web
    r = _get(c, '/playground', follow_redirects=False)
    assert r.status_code == 302 and r.headers['location'] == '/'
    for url in ('/api/playground/worker.js', '/api/playground/sajha.py', '/api/playground/tools'):
        r = _get(c, url, headers={'Accept': 'application/json'}, follow_redirects=False)
        assert r.status_code == 401, url


def test_static_assets_the_page_needs_exist():
    static = ROOT / 'sajha' / 'web' / 'static'
    js = (static / 'vendor' / 'codemirror' / 'codemirror-python.min.js').read_text()
    assert 'SajhaEditor' in js
    assert (static / 'js' / 'playground.js').is_file()
    readme = (static / 'vendor' / 'pyodide' / 'README.md').read_text()
    assert 'fetch_pyodide.py' in readme
    ignore = (static / 'vendor' / 'pyodide' / '.gitignore').read_text()
    assert '*' in ignore.split() and '!README.md' in ignore


# ── headers: only the playground is isolated and may compile WebAssembly ────────

def test_isolation_and_csp_only_on_the_playground(web, vendored):
    c, admin = web
    page = _get(c, '/playground', cookies=admin)
    assert page.headers['cross-origin-opener-policy'] == 'same-origin'
    assert page.headers['cross-origin-embedder-policy'] == 'require-corp'
    assert "worker-src 'self'" in page.headers['content-security-policy']
    assert 'unsafe-eval' not in page.headers['content-security-policy']    # the page runs no Wasm

    w = _get(c, '/api/playground/worker.js', cookies=admin)
    assert w.status_code == 200 and w.headers['content-type'].startswith('text/javascript')
    assert w.headers['cross-origin-embedder-policy'] == 'require-corp'
    csp = w.headers['content-security-policy']
    assert "'wasm-unsafe-eval'" in csp and "'unsafe-eval'" not in csp
    assert 'cdn.jsdelivr.net' not in csp                                 # vendored: self only
    assert 'https://pypi.org' in csp and 'https://files.pythonhosted.org' in csp
    assert 'loadPackagesFromImports' in w.text and 'setInterruptBuffer' in w.text

    for url in ('/dashboard', '/ask', '/tools', '/help'):
        r = _get(c, url, cookies=admin)
        assert r.status_code == 200, url
        assert 'cross-origin-opener-policy' not in r.headers, url
        assert 'cross-origin-embedder-policy' not in r.headers, url
        assert 'wasm-unsafe-eval' not in r.headers['content-security-policy'], url
    r = _get(c, '/')
    assert 'cross-origin-embedder-policy' not in r.headers


def test_cdn_mode_adds_the_cdn_origin_to_the_worker_only(web, vendored, monkeypatch):
    c, admin = web
    monkeypatch.setenv('SAJHA_PLAYGROUND_ASSETS', 'cdn')
    monkeypatch.setenv('SAJHA_PLAYGROUND_ALLOW_PYPI', 'false')
    page = _get(c, '/playground', cookies=admin)
    data = _pg_data(page.text)
    assert data['indexURL'] == f'https://cdn.jsdelivr.net/pyodide/v{pg.DEFAULT_PYODIDE_VERSION}/full/'
    assert data['assetsOk'] is True
    assert 'cdn.jsdelivr.net' not in page.headers['content-security-policy']
    csp = _get(c, '/api/playground/worker.js', cookies=admin).headers['content-security-policy']
    assert 'script-src' in csp and 'https://cdn.jsdelivr.net' in csp.split('script-src')[1].split(';')[0]
    assert 'pypi.org' not in csp


# ── configuration ─────────────────────────────────────────────────────────────

def test_settings_defaults_and_validation(monkeypatch):
    for k in ('ENABLED', 'ASSETS', 'PYODIDE_VERSION', 'ALLOW_PYPI'):
        monkeypatch.delenv(f'SAJHA_PLAYGROUND_{k}', raising=False)
    s = pg.load_settings()
    assert (s.enabled, s.assets, s.pyodide_version, s.allow_pypi, s.errors) == \
        (True, 'vendored', pg.DEFAULT_PYODIDE_VERSION, True, [])

    monkeypatch.setenv('SAJHA_PLAYGROUND_ASSETS', 'ftp')
    monkeypatch.setenv('SAJHA_PLAYGROUND_PYODIDE_VERSION', 'latest')
    s = pg.load_settings()
    assert s.assets == 'vendored' and s.pyodide_version == pg.DEFAULT_PYODIDE_VERSION
    assert len(s.errors) == 2 and 'playground.assets' in s.errors[0] and 'pyodide_version' in s.errors[1]

    monkeypatch.setenv('SAJHA_PLAYGROUND_ASSETS', 'CDN')
    monkeypatch.setenv('SAJHA_PLAYGROUND_PYODIDE_VERSION', 'v0.29.5')
    monkeypatch.setenv('SAJHA_PLAYGROUND_ENABLED', 'no')
    s = pg.load_settings()
    assert (s.assets, s.pyodide_version, s.enabled, s.errors) == ('cdn', '0.29.5', False, [])


def test_shipped_config_and_fetch_script_agree():
    import yaml
    cfg = yaml.safe_load((ROOT / 'config' / 'application.yml').read_text())['playground']
    assert str(cfg['pyodide_version']) == pg.DEFAULT_PYODIDE_VERSION
    assert cfg['assets'] in pg.ASSET_MODES and cfg['enabled'] is True
    spec = importlib.util.spec_from_file_location('fetch_pyodide', ROOT / 'scripts' / 'fetch_pyodide.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert pg.DEFAULT_PYODIDE_VERSION in mod.PINNED_CORE_SHA256         # the default verifies offline
    for want in ('numpy', 'pandas', 'matplotlib', 'scipy', 'scikit-learn', 'statsmodels', 'sympy', 'micropip'):
        assert want in mod.DEFAULT_PACKAGES
    lock = {'packages': {'a': {'depends': ['b']}, 'b': {'depends': ['c']}, 'c': {'depends': []},
                         'd': {'depends': []}}}
    assert mod.closure(lock, ['a']) == ['a', 'b', 'c']
    with pytest.raises(SystemExit):
        mod.closure(lock, ['nope'])


def test_disabled_playground_is_a_friendly_404_and_leaves_the_menus(web, monkeypatch):
    c, admin = web
    monkeypatch.setenv('SAJHA_PLAYGROUND_ENABLED', 'false')
    r = _get(c, '/playground', cookies=admin)
    assert r.status_code == 404
    assert 'Python Playground is switched off' in r.text and 'playground.enabled' in r.text
    assert _get(c, '/api/playground/worker.js', cookies=admin).status_code == 404
    assert 'href="/playground"' not in _get(c, '/dashboard', cookies=admin).text


def test_missing_vendored_assets_show_an_admin_hint(web, vendored, monkeypatch):
    c, admin = web
    monkeypatch.setenv('SAJHA_PLAYGROUND_PYODIDE_VERSION', '0.0.1')           # not vendored
    r = _get(c, '/playground', cookies=admin)
    assert r.status_code == 200
    assert 'id="pgAssetsHint"' in r.text and 'scripts/fetch_pyodide.py' in r.text
    assert 'playground.assets: cdn' in r.text
    assert _pg_data(r.text)['assetsOk'] is False


def test_bad_settings_are_shown_to_admins(web, vendored, monkeypatch):
    c, admin = web
    monkeypatch.setenv('SAJHA_PLAYGROUND_ASSETS', 'ftp')
    r = _get(c, '/playground', cookies=admin)
    assert r.status_code == 200 and 'playground.assets is &#39;ftp&#39;' in r.text


# ── wiring ────────────────────────────────────────────────────────────────────

def test_playground_is_in_the_menu_on_the_dashboard_and_in_studio(web, vendored):
    c, admin = web
    t = _get(c, '/dashboard', cookies=admin).text
    assert t.count('href="/playground"') >= 2                    # Tools menu and a quick action
    tools_menu = t[t.index('<i class="bi bi-tools" aria-hidden="true"></i> Tools'):]
    assert tools_menu.index('Python Playground') < tools_menu.index('>Reports<')
    studio = _get(c, '/studio', cookies=admin).text
    assert 'openInPlayground()' in studio and 'sajha.playground.import' in studio


# ── the sajha bridge module ─────────────────────────────────────────────────────

def test_bridge_and_runtime_sources_are_served(web):
    c, admin = web
    for url, needles in (('/api/playground/sajha.py', ('def call(', 'def tools(', 'def ask(', '/api/tools/execute',
                                                   '/api/ai/ask', 'class ToolError')),
                         ('/api/playground/runtime.py', ('async def run_cell(', 'eval_code_async', '_repr_html_'))):
        r = _get(c, url, cookies=admin)
        assert r.status_code == 200, url
        assert r.headers['content-type'].startswith('text/x-python')
        for n in needles:
            assert n in r.text, (url, n)
        compile(r.text, url, 'exec')                             # valid Python
    assert _get(c, '/api/playground/sajha.py', cookies=admin).text == pg.bridge_source()


def test_playground_tools_api_lists_what_the_user_may_call(web):
    c, admin = web
    r = _get(c, '/api/playground/tools', cookies=admin)
    assert r.status_code == 200
    names = {t['name'] for t in r.json()['tools']}
    assert 'calc_future_value' in names and r.json()['count'] == len(names)


class _FakeXHR:
    """Just enough of the browser's XMLHttpRequest to run the bridge in CPython."""
    client = None
    cookies = None

    @classmethod
    def new(cls):
        return cls()

    def open(self, method, url, is_async):
        assert is_async is False                      # the bridge's calls are synchronous
        self.method, self.url, self.headers = method, url, {}

    def setRequestHeader(self, k, v):
        self.headers[k] = v

    def send(self, body=None):
        c = self.client
        c.cookies.clear()
        r = c.request(self.method, self.url, content=body, headers=self.headers, cookies=self.cookies)
        self.status, self.responseText = r.status_code, r.text


@pytest.fixture
def bridge(web, monkeypatch):
    c, admin = web
    _FakeXHR.client, _FakeXHR.cookies = c, admin
    monkeypatch.setitem(sys.modules, 'js', types.SimpleNamespace(
        XMLHttpRequest=_FakeXHR, location=types.SimpleNamespace(origin='http://testserver')))
    import sajha.studio                                    # the bridge replaces it; put it back after
    monkeypatch.setitem(sys.modules, 'sajha.studio', sys.modules['sajha.studio'])
    mod = types.ModuleType('sajha_bridge_under_test')
    exec(compile(pg.bridge_source(), 'sajha_bridge.py', 'exec'), mod.__dict__)
    return mod


def test_bridge_calls_tools_and_ask_through_the_api(bridge):
    sajha = bridge
    assert 'calc_future_value' in {t['name'] for t in sajha.tools()}
    r = sajha.call('calc_future_value', present_value=1000, rate=10, years=2)
    assert r['future_value'] == 1210.0
    assert sajha.call('calc_future_value', {'present_value': 100, 'rate': 0, 'years': 5})['future_value'] == 100
    with pytest.raises(sajha.ToolError) as e:
        sajha.call('no_such_tool')
    assert e.value.status == 404
    a = sajha.ask('What is the percentage change from 80 to 100?')
    assert a['steps'] and a['steps'][0]['name'] == 'calc_percentage_change'
    assert sajha.server() == 'http://testserver'
    assert sajha.schema('calc_future_value')['name'] == 'calc_future_value'


def test_bridge_reports_an_expired_session(bridge, monkeypatch):
    monkeypatch.setattr(_FakeXHR, 'cookies', {})
    with pytest.raises(bridge.ToolError) as e:
        bridge.call('calc_future_value', present_value=1, rate=1, years=1)
    assert e.value.status == 401 and 'signed in' in str(e.value)


def test_bridge_studio_decorator_is_a_stand_in(bridge):
    deco = bridge.studio.sajhamcptool(description='d', category='Math', tags=['x'])

    def f(n: int) -> dict:
        return {'n': n}
    assert deco(f) is f and f.__sajha_tool__['category'] == 'Math'
