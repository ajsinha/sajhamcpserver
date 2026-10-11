# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Adversarial QA Plan 3.10 (the web console), P0: hostile strings in tool names, titles and descriptions,
notice titles, details and links, and upstream (federated) descriptions are rendered escaped on every
console page that shows them, and every HTML response carries the Content-Security-Policy that blocks
inline script (nonce-only scripts, no inline handlers). Rendered through the TestClient (no browser):
the raw markup must not appear, and the CSP must not allow 'unsafe-inline' scripts. Notices and
upstream descriptions are rendered in the browser from JSON (sajha/web/static/js/notices.js, the
federation page): those renderers are checked statically (every field through ``esc``, links only
same-origin paths).
"""

import re
from pathlib import Path

import pytest

from sajha.tools.base_mcp_tool import BaseMCPTool

PAYLOADS = ('<script>alert(1)</script>', '<img src=x onerror=alert(2)>', '"><svg onload=alert(3)>',
            "</textarea><script>alert(4)</script>", "';alert(5);//")
RAW_MARKUP = ('<script>alert(1)</script>', '<img src=x onerror=alert(2)>', '<svg onload=alert(3)>',
              '</textarea><script>alert(4)</script>')
HOSTILE = ' '.join(PAYLOADS)


class _Hostile(BaseMCPTool):
    def __init__(self, name, desc, title=None, namespaced=False):
        cfg = {'name': name, 'description': desc, 'inputSchema': {
            'type': 'object', 'properties': {'q': {'type': 'string', 'description': desc}}}}
        if title:
            cfg['title'] = title
        super().__init__(cfg)
        self.namespaced_name = namespaced

    def get_input_schema(self):
        return self._input_schema

    def get_output_schema(self):
        return {}

    def execute(self, arguments):
        return {'ok': True}


@pytest.fixture
def hostile_catalog(web):
    from sajha.app import tools_registry
    from sajha import notices
    tools = [_Hostile('zz_adv_xss', HOSTILE, title=HOSTILE),
             _Hostile('zz_adv_x"><script>alert(9)</script>', HOSTILE),
             _Hostile('evilup__zz_adv_define', 'Upstream says: ' + HOSTILE, namespaced=True)]
    for t in tools:
        tools_registry.register_tool(t)
    notices.raise_notice('adversarial.xss', severity='critical', source='tools', title=HOSTILE, detail=HOSTILE,
                         link='javascript:alert(7)', audience='all')
    yield web
    for t in tools:
        tools_registry.unregister_tool(t.name)
    notices.clear_notice('adversarial.xss')


def _assert_escaped(html: str, where: str):
    for raw in RAW_MARKUP:
        assert raw not in html, f'{where}: unescaped {raw!r}'
    assert 'alert(9)</script>' not in html, where
    assert 'href="javascript:' not in html.lower() and "href='javascript:" not in html.lower(), where


PAGES = ['/', '/tools', '/tools/zz_adv_xss/execute', '/tools/zz_adv_xss/schema', '/tools/domains',
         '/admin/federation']


@pytest.mark.parametrize('path', PAGES)
def test_hostile_strings_render_escaped(hostile_catalog, path):
    c, admin = hostile_catalog
    r = c.get(path, cookies=admin)
    if r.status_code == 404:
        pytest.skip(f'{path} is not a page in this build')
    assert r.status_code == 200, (path, r.status_code)
    _assert_escaped(r.text, path)


def test_the_hostile_strings_reach_the_pages_at_all(hostile_catalog):
    """Guard against a vacuous pass: the hostile tool and notice are on the pages, escaped."""
    c, admin = hostile_catalog
    html = c.get('/tools', cookies=admin).text
    assert 'zz_adv_xss' in html and ('&lt;script&gt;alert(1)' in html or '\\u003cscript\\u003ealert(1)' in html)


@pytest.mark.parametrize('path', ['/', '/tools', '/login', '/help', '/glossary'])
def test_every_html_page_carries_a_csp_without_inline_script(web, path):
    c, admin = web
    r = c.get(path, cookies=admin)
    assert r.status_code == 200, path
    csp = r.headers.get('content-security-policy', '')
    script_src = next((d.strip() for d in csp.split(';') if d.strip().startswith('script-src ')), '')
    assert script_src and "'unsafe-inline'" not in script_src and "'nonce-" in script_src, (path, csp)
    assert "script-src-attr 'none'" in csp and "object-src 'none'" in csp and 'frame-ancestors' in csp


WEB = Path(__file__).resolve().parents[2] / 'sajha' / 'web'


def test_the_notice_renderer_escapes_every_field_and_allows_only_local_links():
    js = (WEB / 'static' / 'js' / 'notices.js').read_text(encoding='utf-8')
    assert re.search(r"function esc\(s\)\s*\{[^}]*&amp;[^}]*&lt;[^}]*&gt;[^}]*&quot;[^}]*&#39;", js, re.S)
    raw = re.findall(r"\+\s*n\.(?:title|detail|source|id|acknowledged_by|cleared_reason|severity)\b", js)
    assert not raw, f'notices.js concatenates notice fields into HTML without esc: {raw}'
    assert "href.charAt(0) === '/' && href.charAt(1) !== '/'" in js          # safeLink: same-origin paths only
    assert 'href="\' + esc(link)' in js and 'safeLink(n.link)' in js


def test_the_federation_page_escapes_upstream_text():
    html = (WEB / 'templates' / 'admin' / 'federation.html').read_text(encoding='utf-8')
    assert 'function esc(s)' in html
    for field in ('description', 'title'):
        raw = re.findall(r"\+\s*it\." + field + r"\s*\+", html)
        assert not raw, f'federation.html renders it.{field} without esc: {raw}'
    assert 'esc(it.description)' in html
