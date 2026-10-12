# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The sandbox egress proxy (sajha/sandbox/egress.py, docs/architecture/Sandbox.md section 4).

The first half drives the proxy directly over TCP: an allowlisted host is reachable
through CONNECT and plain HTTP forwarding, an unlisted host is refused, and listed
cloud metadata, loopback and private addresses are refused anyway; every decision is
audited. The second half runs Python tools under each backend that can confine a run
to the proxy (subprocess, bwrap, docker), skipping the ones this host lacks with the
reason, and checks that the proxy is the only way out.
"""

import http.server
import json
import socket
import textwrap
import threading

import pytest

from sajha import sandbox
from sajha.sandbox import egress, policy_from_config
from sajha.sandbox.backends import BACKENDS

BODY = b'HELLO-EGRESS'


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length', str(len(BODY)))
        self.send_header('X-Seen-Path', self.path)
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *a):
        pass


@pytest.fixture
def origin():
    """An HTTP server on the host's loopback: the 'internet' host the tests try to reach."""
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def names(monkeypatch):
    """allowed.test and denied.test resolve to the host's loopback; only allowed.test is exempt from
    the loopback rule (as an operator would exempt an intranet name), so it stands in for a public host."""
    real = egress._default_resolver

    def resolver(host, port):
        if host in ('allowed.test', 'denied.test'):
            return ['127.0.0.1']
        return real(host, port)

    monkeypatch.setattr(egress, '_default_resolver', resolver)
    monkeypatch.setenv('SAJHA_SANDBOX_EGRESS_EXEMPT_HOSTS', 'allowed.test')
    monkeypatch.setenv('SAJHA_SANDBOX_EGRESS_MODE', 'proxy')
    monkeypatch.delenv('SAJHA_SANDBOX_EGRESS_BLOCK_PRIVATE_NETWORKS', raising=False)


@pytest.fixture
def audits(monkeypatch):
    from sajha import audit
    seen = []
    monkeypatch.setattr(audit, 'record', lambda event, **kw: seen.append((event, kw)))
    return seen


def _ask(addr, raw: bytes) -> bytes:
    s = socket.create_connection(addr, timeout=10)
    try:
        s.sendall(raw)
        out = b''
        while True:
            chunk = s.recv(65536)
            if not chunk:
                return out
            out += chunk
    finally:
        s.close()


# ── The proxy on its own ───────────────────────────────────────────────────

def test_parse_allow_hosts_defaults_to_443():
    assert egress.parse_allow_hosts(['API.x.com', 'b.y:8443', '[2001:db8::1]:80', 'x.']) == \
        [('api.x.com', 443), ('b.y', 8443), ('2001:db8::1', 80), ('x', 443)]


def test_decide_rules(names):
    st = egress.load_egress_settings()
    allow = egress.parse_allow_hosts(['allowed.test:80', 'denied.test:80', '169.254.169.254:80',
                                      '10.1.2.3:80', '127.0.0.1:80', 'metadata.google.internal:80',
                                      'localhost:80', '[::1]:80'])
    assert egress.decide('allowed.test', 80, allow, st).allowed
    assert egress.decide('allowed.test', 81, allow, st).reason == 'not in sandbox.allow_hosts'
    assert egress.decide('other.test', 80, allow, st).reason == 'not in sandbox.allow_hosts'
    assert 'loopback' in egress.decide('denied.test', 80, allow, st).reason
    assert 'cloud metadata' in egress.decide('169.254.169.254', 80, allow, st).reason
    assert 'cloud metadata' in egress.decide('metadata.google.internal', 80, allow, st).reason
    assert 'private' in egress.decide('10.1.2.3', 80, allow, st).reason
    assert 'loopback' in egress.decide('127.0.0.1', 80, allow, st).reason
    assert 'loopback' in egress.decide('localhost', 80, allow, st).reason
    assert 'loopback' in egress.decide('::1', 80, allow, st).reason


def test_private_ranges_can_be_allowed_by_the_operator(names, monkeypatch):
    monkeypatch.setenv('SAJHA_SANDBOX_EGRESS_BLOCK_PRIVATE_NETWORKS', 'false')
    st = egress.load_egress_settings()
    allow = egress.parse_allow_hosts(['10.1.2.3:80', '169.254.169.254:80'])
    assert egress.decide('10.1.2.3', 80, allow, st).allowed
    assert not egress.decide('169.254.169.254', 80, allow, st).allowed   # metadata: always


def test_proxy_connect_and_forward(names, origin, audits):
    with egress.EgressProxy([f'allowed.test:{origin}'], run_id='r1', tool='t1') as proxy:
        addr = proxy.start_tcp()
        # CONNECT, then a plain request through the tunnel
        out = _ask(addr, f'CONNECT allowed.test:{origin} HTTP/1.1\r\nHost: allowed.test\r\n\r\n'
                         f'GET /tunnel HTTP/1.0\r\nHost: allowed.test\r\n\r\n'.encode())
        assert out.startswith(b'HTTP/1.1 200') and out.endswith(BODY) and b'/tunnel' in out
        # absolute-URI forwarding: sent on in origin form, proxy headers dropped
        out = _ask(addr, f'GET http://allowed.test:{origin}/fwd?q=1 HTTP/1.1\r\nHost: allowed.test\r\n'
                         f'Proxy-Authorization: Basic eDp5\r\n\r\n'.encode())
        assert out.startswith(b'HTTP/1.0 200') and out.endswith(BODY) and b'X-Seen-Path: /fwd?q=1' in out
        # through urllib, as tool code would do it
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {'http': f'http://{addr[0]}:{addr[1]}'}))
        assert opener.open(f'http://allowed.test:{origin}/u', timeout=10).read() == BODY
    assert proxy.stats['allowed'] == 3 and proxy.stats['denied'] == 0
    assert [a[0] for a in audits] == ['sandbox.egress'] * 3
    ev = audits[0][1]
    assert ev['outcome'] == 'allowed' and ev['resource'] == {'type': 'sandbox_run', 'id': 'r1'}
    assert ev['details']['host'] == 'allowed.test' and ev['details']['tool'] == 't1'


def test_proxy_refuses_unlisted_private_and_metadata(names, origin, audits):
    listed = [f'denied.test:{origin}', '169.254.169.254:80', '10.1.2.3:80', f'127.0.0.1:{origin}']
    with egress.EgressProxy(listed + [f'allowed.test:{origin}'], run_id='r2') as proxy:
        addr = proxy.start_tcp()
        for target in [f'unlisted.test:{origin}', f'allowed.test:{origin + 1}'] + listed:
            out = _ask(addr, f'CONNECT {target} HTTP/1.1\r\n\r\n'.encode())
            assert out.startswith(b'HTTP/1.1 403'), (target, out)
        out = _ask(addr, b'GET http://169.254.169.254/latest/meta-data/ HTTP/1.1\r\nHost: x\r\n\r\n')
        assert out.startswith(b'HTTP/1.1 403') and b'cloud metadata' in out
        assert _ask(addr, b'GET https://allowed.test/ HTTP/1.1\r\n\r\n').startswith(b'HTTP/1.1 400')
        assert _ask(addr, b'garbage\r\n\r\n').startswith(b'HTTP/1.1 400')
    assert proxy.stats['allowed'] == 0 and proxy.stats['denied'] == 7
    assert {a[1]['outcome'] for a in audits} == {'denied'} and len(audits) == 7


def test_proxy_bounds_concurrent_connections(names, origin, monkeypatch):
    monkeypatch.setenv('SAJHA_SANDBOX_EGRESS_MAX_CONNECTIONS', '1')
    with egress.EgressProxy([f'allowed.test:{origin}']) as proxy:
        addr = proxy.start_tcp()
        hold = socket.create_connection(addr, timeout=5)      # occupies the only slot (no head sent)
        try:
            import time
            time.sleep(0.3)
            assert _ask(addr, b'CONNECT allowed.test:1 HTTP/1.1\r\n\r\n').startswith(b'HTTP/1.1 503')
        finally:
            hold.close()


def test_per_run_socket_directory_is_private_and_removed(tmp_path):
    proxy = egress.start_for_run('sajha-sbx-testrun', ['a.example:443'], base=str(tmp_path))
    d = tmp_path / 'sajha-sbx-testrun.egress'
    assert (d / 'egress.sock').exists() and (d.stat().st_mode & 0o777) == 0o700
    with pytest.raises(FileExistsError):                       # a pre-created directory is refused
        egress.start_for_run('sajha-sbx-testrun', ['a.example:443'], base=str(tmp_path))
    egress.stop_for_run(proxy)
    assert not d.exists()


# ── Through the sandbox backends ───────────────────────────────────────────

def _backend(name):
    sandbox.reset()
    b = BACKENDS[name](sandbox.load_settings())
    ok, why = b.available()
    if not ok:
        pytest.skip(f'sandbox backend {name} not available here: {why}')
    if not b.supports_egress_proxy:
        pytest.skip(f'sandbox backend {name} cannot use the egress proxy on this platform')
    return b


def _attempt(backend, body, arguments, **policy):
    src = ('from sajha.tools.base_mcp_tool import BaseMCPTool\n'
           'class T(BaseMCPTool):\n'
           '    def execute(self, a):\n'
           '        try:\n' + textwrap.indent(textwrap.dedent(body), ' ' * 12) +
           '\n        except BaseException as e:\n'
           '            out = "ERR:" + type(e).__name__ + ":" + str(e)\n'
           '        return out\n')
    policy.setdefault('timeout_seconds', 60)
    res = backend.run({'op': 'python_tool', 'source': src, 'class_name': 'T', 'arguments': arguments,
                       'tool_config': {'name': 't'}, 'tool': 'egress-test'}, policy_from_config(policy))
    payload = json.loads(res.stdout) if res.stdout.strip().startswith('{') else None
    if payload is None and res.runner_error and 'network namespace' in res.runner_error:
        pytest.skip(f'{backend.name}: {res.runner_error}')
    assert payload and payload['ok'], (res.stdout, res.stderr, res.runner_error)
    return payload['result'], payload.get('applied') or {}


TOOL_BODY = '''
import os, socket, urllib.request, urllib.error
r = {}
r["proxy_env"] = os.environ.get("HTTPS_PROXY")
r["allowed"] = urllib.request.urlopen("http://allowed.test:%d/in" % a["port"], timeout=10).read().decode()
s = socket.create_connection(("127.0.0.1", 3128), timeout=10)
s.sendall(("CONNECT allowed.test:%d HTTP/1.1\\r\\n\\r\\nGET /tunnel HTTP/1.0\\r\\n\\r\\n" % a["port"]).encode())
buf = b""
while True:
    c = s.recv(65536)
    if not c:
        break
    buf += c
r["connect"] = buf.decode("latin-1")
def code(url):
    try:
        urllib.request.urlopen(url, timeout=10)
        return "OPEN"
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return "ERR:" + type(e).__name__
r["denied"] = code("http://denied.test:%d/" % a["port"])
r["unlisted"] = code("http://unlisted.test:%d/" % a["port"])
r["metadata"] = code("http://169.254.169.254/latest/meta-data/")
r["private"] = code("http://10.1.2.3/")
r["loopback"] = code("http://127.0.0.1:%d/" % a["port"])
def direct(host, port):
    try:
        socket.create_connection((host, port), timeout=3).close()
        return "CONNECTED"
    except Exception as e:
        return "ERR:" + type(e).__name__
r["direct_host_loopback"] = direct("127.0.0.1", a["port"])
r["direct_internet"] = direct("1.1.1.1", 80)
r["direct_on_bridge_port"] = direct("1.1.1.1", 3128)   # the one port Landlock admits: no route anyway
try:
    socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    r["unix_socket"] = "ALLOWED"
except OSError as e:
    r["unix_socket"] = "ERR"
out = r
'''


@pytest.mark.parametrize('name', ['subprocess', 'bwrap', 'docker'])
def test_proxy_is_the_only_way_out(name, names, origin, audits):
    backend = _backend(name)
    allow = [f'allowed.test:{origin}', f'denied.test:{origin}', '169.254.169.254:80', '10.1.2.3:80',
             f'127.0.0.1:{origin}', '1.1.1.1:80']
    allow.remove(f'denied.test:{origin}')                    # denied.test stays unlisted on purpose
    r, applied = _attempt(backend, TOOL_BODY, {'port': origin}, network='allowlist', allow_hosts=allow)
    assert isinstance(r, dict), r
    assert r['proxy_env'] == 'http://127.0.0.1:3128'
    assert r['allowed'] == BODY.decode()
    assert r['connect'].startswith('HTTP/1.1 200') and r['connect'].endswith(BODY.decode())
    assert r['denied'] == 403 and r['unlisted'] == 403
    assert r['metadata'] == 403 and r['private'] == 403 and r['loopback'] == 403
    # no route but the proxy: the host's loopback is not this sandbox's, the internet has no route
    assert r['direct_host_loopback'].startswith('ERR:'), r
    assert r['direct_internet'].startswith('ERR:'), r
    assert r['direct_on_bridge_port'].startswith('ERR:'), r
    assert applied.get('egress', {}).get('bridge_port') == 3128
    if name != 'docker' and applied.get('seccomp'):
        assert r['unix_socket'] == 'ERR'                      # the proxy socket is not reachable directly
    events = [kw for ev, kw in audits if ev == 'sandbox.egress']
    assert sum(1 for e in events if e['outcome'] == 'allowed') == 2
    assert {e['details']['host'] for e in events if e['outcome'] == 'denied'} >= \
        {'denied.test', 'unlisted.test', '169.254.169.254', '10.1.2.3', '127.0.0.1'}
    assert all(e['details']['tool'] == 'egress-test' for e in events)


def test_network_off_stays_off_without_proxy(names, origin):
    backend = _backend('subprocess')
    r, applied = _attempt(backend, 'import os\nout = [os.environ.get("HTTPS_PROXY")]', {})
    assert r == [None] and 'egress' not in applied


def test_direct_mode_keeps_library_level_check(names, monkeypatch, origin):
    monkeypatch.setenv('SAJHA_SANDBOX_EGRESS_MODE', 'direct')
    backend = _backend('subprocess')
    r, applied = _attempt(backend, 'import os\nout = os.environ.get("HTTPS_PROXY")', {},
                          network='allowlist', allow_hosts=[f'127.0.0.1:{origin}'])
    assert r is None and 'egress' not in applied


def test_status_reports_egress(names):
    st = sandbox.status(probe=False)
    assert st['egress']['mode'] == 'proxy' and st['egress']['block_private_networks'] is True
    assert any(g['guarantee'].startswith('Allowlisted network only through the egress proxy')
               for g in BACKENDS['bwrap'](sandbox.load_settings()).guarantees(probe=False))


def test_long_lived_container_network_args(names, origin, audits):
    """A container running someone else's program (a federated stdio upstream) with network: allowlist
    joins a loopback-only sidecar bridged to the proxy; both end with the container."""
    import shutil
    import subprocess
    import time
    import uuid
    b = BACKENDS['docker'](sandbox.load_settings())
    ok, why = b.available()
    if not ok:
        pytest.skip(f'docker backend not available here: {why}')
    assert b.network_args(policy_from_config({}), 'x') == ['--network', 'none']
    name = f'sajha-egress-test-{uuid.uuid4().hex[:8]}'
    pol = policy_from_config({'network': 'allowlist', 'allow_hosts': [f'allowed.test:{origin}']})
    args = b.network_args(pol, name)
    assert args[:2] == ['--network', f'container:{name}-egress'] and '-e' in args
    prog = textwrap.dedent('''
        import os, socket, sys, urllib.request, urllib.error
        port = int(sys.argv[1])
        print(urllib.request.urlopen("http://allowed.test:%d/" % port, timeout=10).read().decode())
        try:
            urllib.request.urlopen("http://denied.test:%d/" % port, timeout=10)
            print("DENIED-OPEN")
        except urllib.error.HTTPError as e:
            print("DENIED-%d" % e.code)
        try:
            socket.create_connection(("1.1.1.1", 80), timeout=3)
            print("DIRECT-OPEN")
        except OSError:
            print("DIRECT-ERR")
    ''')
    docker = shutil.which(b.binary()) or b.binary()
    r = subprocess.run([docker, 'run', '--rm', '--name', name, *args, '--user', '65534:65534', '--read-only',
                        '--cap-drop', 'ALL', b.image(), 'python3', '-c', prog, str(origin)],
                       capture_output=True, text=True, timeout=120, env=b.launch_env())
    assert r.stdout.split() == ['HELLO-EGRESS', 'DENIED-403', 'DIRECT-ERR'], (r.stdout, r.stderr)
    events = [kw for ev, kw in audits if ev == 'sandbox.egress']
    assert {(e['outcome'], e['details']['host']) for e in events} == {('allowed', 'allowed.test'),
                                                                        ('denied', 'denied.test')}
    assert all(e['resource']['id'] == name for e in events)
    deadline = time.time() + 30                               # the sidecar and proxy end with the container
    while time.time() < deadline and name in egress._CONTAINERS:
        time.sleep(0.5)
    assert name not in egress._CONTAINERS
    left = subprocess.run([docker, 'ps', '-a', '-q', '--filter', f'name={name}-egress'], capture_output=True,
                          text=True, timeout=30, env=b.launch_env())
    assert left.stdout.strip() == ''
