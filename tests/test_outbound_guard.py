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
    monkeypatch.delenv('SAJHA_TOOLS_OUTBOUND_PROXY', raising=False)
    monkeypatch.delenv('SAJHA_TOOLS_OUTBOUND_NO_PROXY', raising=False)
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


# ── through tools.outbound.proxy ──

class _ProxyHandler(BaseHTTPRequestHandler):
    """A stand-in HTTP proxy: answers every absolute-form request itself, naming what it was asked."""
    seen = []

    def do_GET(self):
        import json
        type(self).seen.append({'target': self.path, 'proxy_auth': self.headers.get('Proxy-Authorization')})
        if 'to-metadata' in self.path:
            self.send_response(302)
            self.send_header('Location', 'http://169.254.169.254/latest/meta-data/')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        body = json.dumps({'via': 'proxy', 'target': self.path}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture()
def proxy_server(monkeypatch):
    _ProxyHandler.seen = []
    srv = ThreadingHTTPServer(('127.0.0.1', 0), _ProxyHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{srv.server_address[1]}'
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_PROXY', url)
    monkeypatch.delenv('SAJHA_TOOLS_OUTBOUND_NO_PROXY', raising=False)
    yield url
    srv.shutdown()
    srv.server_close()


def test_requests_go_through_the_configured_proxy(proxy_server, monkeypatch):
    _fake_dns(monkeypatch, {'public.example': ['93.184.216.34']})
    r = outbound.request('GET', 'http://public.example/page?q=1')
    assert r.json() == {'via': 'proxy', 'target': 'http://public.example/page?q=1'}
    assert outbound.vet('http://public.example/')[2] is None      # not pinned: the proxy connects


def test_the_proxy_never_comes_from_the_environment_proxy_variables(monkeypatch):
    monkeypatch.delenv('SAJHA_TOOLS_OUTBOUND_PROXY', raising=False)
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:1')
    assert outbound.proxy_url() == '' and outbound.vet('http://93.184.216.34/')[2] == '93.184.216.34'


@pytest.mark.parametrize('url', ['http://169.254.169.254/latest/meta-data/', 'http://metadata.google.internal/',
                                 'http://localhost/', 'http://2130706433/', 'http://[::ffff:127.0.0.1]/'])
def test_blocked_names_and_literals_are_refused_before_the_proxy_is_asked(proxy_server, url):
    with pytest.raises(outbound.Refused):
        outbound.request('GET', url)
    assert _ProxyHandler.seen == []


def test_a_name_resolving_to_a_blocked_address_is_refused_through_the_proxy(proxy_server, monkeypatch):
    _fake_dns(monkeypatch, {'rebind.example': ['93.184.216.34', '127.0.0.1']})
    with pytest.raises(outbound.Refused, match='loopback'):
        outbound.request('GET', 'http://rebind.example/')
    assert _ProxyHandler.seen == []


def test_an_unresolvable_host_goes_to_the_proxy_but_fails_direct(proxy_server, monkeypatch):
    r = outbound.request('GET', 'http://only-the-proxy-knows.invalid/x')
    assert r.json()['target'] == 'http://only-the-proxy-knows.invalid/x'
    monkeypatch.delenv('SAJHA_TOOLS_OUTBOUND_PROXY')
    with pytest.raises(outbound.FetchError, match='does not resolve'):
        outbound.request('GET', 'http://only-the-proxy-knows.invalid/x')


def test_no_proxy_hosts_go_direct(proxy_server, local_server, monkeypatch):
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_EXEMPT_HOSTS', '127.0.0.1/32')
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_NO_PROXY', '127.0.0.0/8')
    r = outbound.request('GET', local_server + '/page')
    assert b'Local page' in r.content and _ProxyHandler.seen == []
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_NO_PROXY', 'intranet.corp.test')
    _fake_dns(monkeypatch, {'intranet.corp.test': ['10.1.2.3']})
    assert outbound.vet('http://intranet.corp.test/')[2] == '10.1.2.3'


def test_a_redirect_to_a_blocked_address_through_the_proxy_is_refused(proxy_server, monkeypatch):
    _fake_dns(monkeypatch, {'public.example': ['93.184.216.34']})
    with pytest.raises(outbound.Refused, match='169.254.169.254'):
        outbound.request('GET', 'http://public.example/to-metadata')
    assert len(_ProxyHandler.seen) == 1            # the second hop never reached the proxy


def test_proxy_credentials_are_sent_but_never_shown(proxy_server, monkeypatch, caplog):
    port = proxy_server.rsplit(':', 1)[1]
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_PROXY', f'http://agent:s3cr%40t@127.0.0.1:{port}')
    _fake_dns(monkeypatch, {'public.example': ['93.184.216.34']})
    outbound.request('GET', 'http://public.example/')
    assert _ProxyHandler.seen[-1]['proxy_auth'].startswith('Basic ')
    # an unreachable proxy: the error and the logs carry no credentials
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        dead = s.getsockname()[1]
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_PROXY', f'http://agent:s3cr%40t@127.0.0.1:{dead}')
    with caplog.at_level('DEBUG'):
        with pytest.raises(outbound.FetchError) as e:
            outbound.request('GET', 'http://public.example/', timeout=3)
    for text in (str(e.value), caplog.text):
        assert 's3cr' not in text and 'agent:' not in text
    assert outbound.mask_proxy(f'http://agent:s3cr%40t@127.0.0.1:{dead}') == f'http://***@127.0.0.1:{dead}'


def test_an_invalid_proxy_setting_is_an_error_without_its_credentials(monkeypatch):
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_PROXY', 'socks5://u:pw123@proxy:1080')
    with pytest.raises(outbound.FetchError) as e:
        outbound.vet('http://93.184.216.34/')
    assert 'tools.outbound.proxy' in str(e.value) and 'pw123' not in str(e.value)


def test_https_goes_through_the_proxy_by_connect_to_the_real_host(monkeypatch):
    import httpx
    seen = {}

    class Capture(httpx.Client):
        def __init__(self, *a, **kw):
            seen['proxy'] = kw.get('proxy')
            seen['trust_env'] = kw.get('trust_env')
            super().__init__(*a, **kw)

        def stream(self, method, url, **kw):
            seen['url'], seen['ext'] = str(url), kw.get('extensions')
            raise httpx.ConnectError('stop here')
    monkeypatch.setattr(httpx, 'Client', Capture)
    monkeypatch.setenv('SAJHA_TOOLS_OUTBOUND_PROXY', 'http://proxy.corp.test:3128')
    _fake_dns(monkeypatch, {'api.example': ['93.184.216.34']})
    with pytest.raises(outbound.FetchError):
        outbound.request('GET', 'https://api.example/v1')
    assert seen == {'proxy': 'http://proxy.corp.test:3128', 'trust_env': False,
                    'url': 'https://api.example/v1', 'ext': {}}
