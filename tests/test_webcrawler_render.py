# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Web crawler: PDF and plain-text pages read as text, and JavaScript rendering through Playwright
(sajha/tools/impl/webcrawler_render.py) with every request the browser makes fetched through the
outbound guard: a local page whose script fills the DOM from a same-origin fetch, while its requests
to another loopback address and to the cloud metadata address are refused and never reach anything;
off unless switched on; request limits; crawl_url's page cap.

Docs: docs/tools/search/Web Crawler Tool Reference Guide.md
"""

import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sajha.core import outbound
from sajha.tools.impl import webcrawler_render as wr
from sajha.tools.impl import webcrawler_tool_refactored as wc
from tests.tool_config_files import read_tool


def _tool(cls, name):
    return cls(read_tool(name))


# ── a minimal PDF: one page of text, a title and a link annotation ──

def make_pdf(text='Hello PDF world', title='Quarterly Report', uri='https://example.org/annex'):
    stream = f'BT /F1 18 Tf 72 720 Td ({text}) Tj ET'.encode()
    objs = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R '
        b'/Resources << /Font << /F1 5 0 R >> >> /Annots [6 0 R] >>',
        b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Type /Annot /Subtype /Link /Rect [72 700 300 720] /A << /S /URI /URI (' + uri.encode() + b') >> >>',
        b'<< /Title (' + title.encode() + b') >>',
    ]
    out, offsets = bytearray(b'%PDF-1.4\n'), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b'%d 0 obj\n' % i + body + b'\nendobj\n'
    xref = len(out)
    out += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)
    for off in offsets:
        out += b'%010d 00000 n \n' % off
    out += b'trailer\n<< /Size %d /Root 1 0 R /Info 7 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, xref)
    return bytes(out)


def _respond(monkeypatch, body: bytes, ctype: str):
    monkeypatch.setattr(outbound, 'vet', lambda url: ('example.org', 443, '93.184.216.34'))
    monkeypatch.setattr(outbound, 'request', lambda method, url, **kw: outbound.Response(
        200, 'OK', {'Content-Type': ctype}, body, url))


def test_pdf_pages_are_read_as_text_with_title_and_links(monkeypatch):
    _respond(monkeypatch, make_pdf(), 'application/pdf')
    out = _tool(wc.ExtractContentTool, 'extract_content').execute({'url': 'https://example.org/r.pdf'})
    assert out['title'] == 'Quarterly Report' and 'Hello PDF world' in out['text_content']
    links = _tool(wc.ExtractLinksTool, 'extract_links').execute({'url': 'https://example.org/r.pdf'})
    assert [l['url'] for l in links['links']] == ['https://example.org/annex']


def test_a_pdf_served_with_a_generic_type_is_still_recognised(monkeypatch):
    _respond(monkeypatch, make_pdf(text='Sniffed'), 'application/octet-stream')
    out = _tool(wc.ExtractContentTool, 'extract_content').execute({'url': 'https://example.org/download?id=1'})
    assert 'Sniffed' in out['text_content']


def test_plain_text_is_returned_as_is(monkeypatch):
    _respond(monkeypatch, b'line one\nline two & more', 'text/plain; charset=utf-8')
    out = _tool(wc.ExtractContentTool, 'extract_content').execute({'url': 'https://example.org/notes.txt'})
    assert out['text_content'] == 'line one line two & more' and out['title'] is None


def test_a_broken_pdf_is_an_error_not_garbage(monkeypatch):
    _respond(monkeypatch, b'%PDF-1.4 truncated' + zlib.compress(b'x'), 'application/pdf')
    with pytest.raises(ValueError, match='PDF'):
        _tool(wc.ExtractContentTool, 'extract_content').execute({'url': 'https://example.org/bad.pdf'})


# ── JavaScript rendering ────────────────────────────────────────────

def _chromium_ok() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


needs_browser = pytest.mark.skipif(not _chromium_ok(), reason='Playwright with Chromium is not installed')


class Site:
    def __init__(self):
        self.hits = []


def _site_handler(site, other_port_ref):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            site.hits.append(self.path)
            other = f'http://127.0.0.2:{other_port_ref["port"]}'
            if self.path == '/data.json':
                body, ctype = b'{"msg": "filled by script"}', 'application/json'
            elif self.path.startswith('/many'):
                imgs = ''.join(f'<script src="/s{i}.js"></script>' for i in range(10))
                body, ctype = f'<html><body>{imgs}<p>many</p></body></html>'.encode(), 'text/html'
            elif self.path.startswith('/s'):
                body, ctype = b'var x = 1;', 'application/javascript'
            elif self.path == '/doc.pdf':
                body, ctype = make_pdf(text='Rendered PDF'), 'application/pdf'
            else:
                body = f'''<html><head><title>JS page</title>
<script src="{other}/evil.js"></script></head>
<body><h1>Static heading</h1><div id="out">waiting</div>
<iframe src="{other}/frame"></iframe>
<script>
fetch("http://169.254.169.254/latest/meta-data/").catch(function () {{}});
fetch("/data.json").then(function (r) {{ return r.json(); }}).then(function (d) {{
  document.getElementById("out").textContent = d.msg;
  var a = document.createElement("a"); a.href = "/later"; a.textContent = "later"; document.body.appendChild(a);
}});
</script></body></html>'''.encode()
                ctype = 'text/html'
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return H


@pytest.fixture
def sites(monkeypatch):
    main, other = Site(), Site()
    ref = {}
    s2 = ThreadingHTTPServer(('127.0.0.2', 0), _site_handler(other, ref))
    ref['port'] = s2.server_address[1]
    s1 = ThreadingHTTPServer(('127.0.0.1', 0), _site_handler(main, ref))
    for s in (s1, s2):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    main.url = f'http://127.0.0.1:{s1.server_address[1]}'
    other.url = f'http://127.0.0.2:{ref["port"]}'
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_EXEMPT_HOSTS', '127.0.0.1')      # the page's own server only
    monkeypatch.setenv('SAJHA_TOOLS_WEBCRAWLER_JAVASCRIPT_ENABLED', 'true')
    yield main, other
    s1.shutdown()
    s2.shutdown()


def test_rendering_is_off_unless_enabled(monkeypatch):
    monkeypatch.delenv('SAJHA_TOOLS_WEBCRAWLER_JAVASCRIPT_ENABLED', raising=False)
    monkeypatch.setattr(outbound, 'vet', lambda url: ('example.org', 443, '93.184.216.34'))
    with pytest.raises(wr.RenderUnavailable, match='tools.webcrawler.javascript.enabled'):
        _tool(wc.ExtractContentTool, 'extract_content').execute({'url': 'https://example.org/', 'render_js': True})
    with pytest.raises(ValueError, match='tools.webcrawler.javascript.enabled'):
        _tool(wc.CrawlURLTool, 'crawl_url').execute({'url': 'https://example.org/', 'render_js': True,
                                                     'respect_robots': False})


@needs_browser
def test_rendered_page_runs_its_script_and_every_request_is_guarded(sites):
    main, other = sites
    out = _tool(wc.ExtractContentTool, 'extract_content').execute({'url': f'{main.url}/', 'render_js': True})
    assert out['rendered'] is True and out['title'] == 'JS page'
    assert 'filled by script' in out['text_content'] and 'Static heading' in out['headings']['h1']
    blocked = ' '.join(out['blocked_requests'])
    assert '127.0.0.2' in blocked and '169.254.169.254' in blocked
    assert other.hits == []                                    # the refused server saw nothing
    assert '/data.json' in main.hits                           # the same-origin fetch went through the guard
    links = _tool(wc.ExtractLinksTool, 'extract_links').execute({'url': f'{main.url}/', 'render_js': True})
    assert f'{main.url}/later' in [l['url'] for l in links['links']]       # a link the script added


@needs_browser
def test_without_render_js_the_script_does_not_run(sites):
    main, _ = sites
    out = _tool(wc.ExtractContentTool, 'extract_content').execute({'url': f'{main.url}/'})
    assert 'rendered' not in out and 'waiting' in out['text_content'] and 'filled by script' not in out['text_content']


@needs_browser
def test_a_refused_start_url_never_starts_a_browser(sites):
    _, other = sites
    with pytest.raises(outbound.Refused):
        _tool(wc.ExtractContentTool, 'extract_content').execute({'url': f'{other.url}/', 'render_js': True})
    assert other.hits == []


@needs_browser
def test_request_limit_truncates_the_render(sites, monkeypatch):
    main, _ = sites
    monkeypatch.setenv('SAJHA_TOOLS_WEBCRAWLER_JAVASCRIPT_MAX_REQUESTS', '3')
    out = _tool(wc.GetPageInfoTool, 'get_page_info').execute({'url': f'{main.url}/many', 'render_js': True})
    assert out['render_truncated'] is True and out['requests'] == 3


@needs_browser
def test_a_pdf_opened_with_rendering_is_read_as_text(sites):
    main, _ = sites
    out = _tool(wc.ExtractContentTool, 'extract_content').execute({'url': f'{main.url}/doc.pdf', 'render_js': True})
    assert 'Rendered PDF' in out['text_content']


@needs_browser
def test_crawl_url_caps_rendered_pages(sites, monkeypatch):
    main, _ = sites
    monkeypatch.setenv('SAJHA_TOOLS_WEBCRAWLER_JAVASCRIPT_MAX_PAGES', '1')
    out = _tool(wc.CrawlURLTool, 'crawl_url').execute({'url': f'{main.url}/', 'render_js': True, 'max_pages': 5,
                                                       'respect_robots': False, 'delay': 0})
    assert out['max_pages'] == 1 and out['pages_crawled'] == 1 and out['pages'][0]['rendered'] is True
