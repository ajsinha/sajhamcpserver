# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The outbound fetch guard for tools (sajha/core/outbound.py): the web crawler tools and Studio REST
tools refuse cloud metadata and loopback destinations by default, allow private ranges unless
``tools.outbound.block_private_networks`` is on, never refuse ``tools.outbound.exempt_hosts``, check
every resolved address and every redirect hop.
"""

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sajha.core import outbound


@pytest.fixture(autouse=True)
def _defaults(monkeypatch):
    monkeypatch.delenv('SAJHA_TOOLS_OUTBOUND_BLOCK_PRIVATE_NETWORKS', raising=False)
    monkeypatch.delenv('SAJHA_TOOLS_OUTBOUND_EXEMPT_HOSTS', raising=False)


def _fake_dns(monkeypatch, table):
    """Resolve host names from ``table`` ({host: [addresses]}) instead of the network."""
    real = socket.getaddrinfo

    def fake(host, port, *a, **kw):
        if host in table:
            return [(socket.AF_INET6 if ':' in a_ else socket.AF_INET, socket.SOCK_STREAM, 6, '',
                     (a_, port)) for a_ in table[host]]
        return real(host, port, *a, **kw)
    monkeypatch.setattr(socket, 'getaddrinfo', fake)


@pytest.mark.parametrize('url', ['http://169.254.169.254/latest/meta-data/', 'http://[fd00:ec2::254]/',
                                 'http://metadata.google.internal/computeMetadata/v1/', 'http://169.254.1.1/',
                                 'http://[fe80::1]/', 'http://127.0.0.1:8080/', 'http://127.9.9.9/',
                                 'http://[::1]/', 'http://localhost/admin', 'http://api.localhost/',
                                 'http://0.0.0.0/', 'http://[::]/'])
def test_metadata_and_loopback_are_refused_by_default(url):
    with pytest.raises(outbound.Refused) as e:
        outbound.vet(url)
    assert 'blocked address' in str(e.value) and outbound.EXEMPT_KEY in str(e.value)


@pytest.mark.parametrize('url', ['http://10.0.0.5/', 'http://172.16.3.4/', 'http://192.168.1.1/',
                                 'http://100.64.0.1/', 'http://[fc00::1]/', 'http://[fd12:3456::1]/'])
def test_private_ranges_are_allowed_by_default_and_refused_with_the_switch(url, monkeypatch):
    assert outbound.vet(url)[2]
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_BLOCK_PRIVATE_NETWORKS', 'true')
    with pytest.raises(outbound.Refused, match=r'\(private\)'):
        outbound.vet(url)


def test_public_addresses_pass():
    assert outbound.vet('https://93.184.216.34/x?q=1') == ('93.184.216.34', 443, '93.184.216.34')


@pytest.mark.parametrize('url', ['http://2130706433/', 'http://0177.0.0.1/', 'http://0x7f000001/',
                                 'http://0x7f.1/', 'http://127.1/', 'http://[::ffff:127.0.0.1]/',
                                 'http://[::ffff:a9fe:a9fe]/', 'http://[64:ff9b::a9fe:a9fe]/',
                                 'http://[2002:a9fe:a9fe::1]/', 'http://2852039166/'])
def test_odd_ip_literal_forms_are_normalised(url):
    with pytest.raises(outbound.Refused):
        outbound.vet(url)


def test_a_host_name_resolving_to_a_blocked_address_is_refused(monkeypatch):
    _fake_dns(monkeypatch, {'evil.example': ['93.184.216.34', '169.254.169.254'],
                            'fine.example': ['93.184.216.34', '10.1.2.3']})
    with pytest.raises(outbound.Refused, match='cloud metadata'):
        outbound.vet('http://evil.example/')      # every address is checked, not just the first
    assert outbound.vet('http://fine.example/')[0] == 'fine.example'


def test_exempt_hosts_bypass_the_block(monkeypatch):
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_EXEMPT_HOSTS', 'localhost,127.0.0.0/8,*.corp.test')
    _fake_dns(monkeypatch, {'svc.corp.test': ['10.9.9.9']})
    assert outbound.vet('http://127.0.0.1:9000/')[2] == '127.0.0.1'
    assert outbound.vet('http://localhost:9000/')[0] == 'localhost'
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_BLOCK_PRIVATE_NETWORKS', 'true')
    assert outbound.vet('http://svc.corp.test/')[2] == '10.9.9.9'
    with pytest.raises(outbound.Refused):
        outbound.vet('http://169.254.169.254/')   # not listed: still refused


def test_non_http_and_credential_urls_are_refused():
    for url in ('file:///etc/passwd', 'gopher://x/', 'http://user:pw@93.184.216.34/'):
        with pytest.raises(outbound.Refused):
            outbound.vet(url)


def test_a_refusal_is_logged_at_warning_without_the_query_string(caplog):
    with caplog.at_level('WARNING', logger='sajha.core.outbound'):
        with pytest.raises(outbound.Refused) as e:
            outbound.vet('http://169.254.169.254/latest?token=s3cret')
    assert 's3cret' not in str(e.value) and 's3cret' not in caplog.text
    assert any(r.levelname == 'WARNING' and '169.254.169.254' in r.getMessage() for r in caplog.records)


# ── against a local server (exempted through config, the default untouched) ──

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/to-metadata'):
            self.send_response(302)
            self.send_header('Location', 'http://169.254.169.254/latest/meta-data/')
            self.end_headers()
            return
        if self.path.startswith('/echo'):
            import json
            body = json.dumps({'path': self.path, 'auth': self.headers.get('Authorization')}).encode()
            ctype = 'application/json'
        elif self.path.startswith('/robots.txt'):
            body = b'User-agent: *\nDisallow: /private\n'
            ctype = 'text/plain'
        else:
            body = b'<html><head><title>Local page</title></head><body><a href="/b">b</a></body></html>'
            ctype = 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def local_server():
    srv = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{srv.server_address[1]}'
    srv.shutdown()
    srv.server_close()


def test_a_local_server_is_refused_unless_exempt(local_server, monkeypatch):
    from sajha.tools.impl.webcrawler_tool_refactored import ExtractContentTool, CheckRobotsTxtTool
    with pytest.raises(outbound.Refused):
        ExtractContentTool().execute({'url': local_server + '/page'})
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_EXEMPT_HOSTS', '127.0.0.1/32')
    out = ExtractContentTool().execute({'url': local_server + '/page'})
    assert out['title'] == 'Local page'
    robots = CheckRobotsTxtTool().execute({'url': local_server + '/private/x'})
    assert robots['can_fetch'] is False


def test_a_redirect_to_a_blocked_address_is_refused(local_server, monkeypatch):
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_EXEMPT_HOSTS', '127.0.0.1/32')
    with pytest.raises(outbound.Refused, match='169.254.169.254'):
        outbound.request('GET', local_server + '/to-metadata')
    from sajha.tools.impl.webcrawler_tool_refactored import ExtractContentTool
    with pytest.raises(outbound.Refused):
        ExtractContentTool().execute({'url': local_server + '/to-metadata'})


def test_a_refused_tool_call_is_a_tool_error_not_a_trace(caplog):
    from sajha.tools.impl.webcrawler_tool_refactored import ExtractContentTool
    tool = ExtractContentTool()
    with caplog.at_level('WARNING'):
        with pytest.raises(outbound.Refused) as e:
            tool.execute_with_tracking({'url': 'http://169.254.169.254/latest/meta-data/'})
    assert str(e.value).startswith('refused: http://169.254.169.254/latest/meta-data/ resolves to a blocked '
                                   'address (cloud metadata)')
    assert not any(r.exc_info for r in caplog.records if 'refused' in r.getMessage().lower())


def test_a_studio_rest_tool_calls_an_exempt_local_endpoint(local_server, monkeypatch, tmp_path):
    import importlib.util
    from sajha.studio import RESTToolDefinition, RESTToolGenerator
    d = RESTToolDefinition(name='zz_local_rest', endpoint=local_server + '/echo/{item}', method='GET',
                           description='d', request_schema={'type': 'object', 'properties': {
                               'item': {'type': 'string'}, 'q': {'type': 'string'}}}, response_schema={},
                           basic_auth_username='u', basic_auth_password='p')
    impl = tmp_path / 'rest_zz_local_rest.py'
    impl.write_text(RESTToolGenerator().generate_python_implementation(d), encoding='utf-8')
    spec = importlib.util.spec_from_file_location('rest_zz_local_rest', impl)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tool = mod.RESTZzLocalRestTool()
    with pytest.raises(outbound.Refused):
        tool.execute({'item': '7', 'q': 'x'})
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_EXEMPT_HOSTS', '127.0.0.1')
    out = tool.execute({'item': '7', 'q': 'x'})
    assert out['success'], out
    assert out['data']['path'].startswith('/echo/7?') and 'q=x' in out['data']['path']
    assert out['data']['auth'] == 'Basic dTpw'
