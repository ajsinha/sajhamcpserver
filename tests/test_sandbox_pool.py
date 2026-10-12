# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The docker backend's warm container pool (sajha/sandbox/pool.py, docs/architecture/Sandbox.md).

Needs a reachable Docker daemon and the configured image (``sandbox.docker.image``); every
test is skipped with the reason otherwise. Checks reuse and the reset between calls (files,
processes, shared memory), recreation, the size bound, health checks, a timed-out call, and
the egress proxy through a pooled container.
"""

import json
import shutil
import subprocess
import textwrap
import time

import pytest

from sajha import sandbox
from sajha.sandbox import pool as pool_mod
from sajha.sandbox import policy_from_config
from sajha.sandbox.backends import BACKENDS


@pytest.fixture
def docker_backend(monkeypatch):
    def make(size='1', reset='reuse', max_uses='20'):
        monkeypatch.setenv('SAJHA_SANDBOX_DOCKER_POOL_SIZE', size)
        monkeypatch.setenv('SAJHA_SANDBOX_DOCKER_POOL_RESET', reset)
        monkeypatch.setenv('SAJHA_SANDBOX_DOCKER_POOL_MAX_USES', max_uses)
        monkeypatch.setenv('SAJHA_SANDBOX_DOCKER_POOL_HEALTH_INTERVAL_SECONDS', '600')
        sandbox.reset()
        b = BACKENDS['docker'](sandbox.load_settings())
        ok, why = b.available()
        if not ok:
            pytest.skip(f'docker backend not available here: {why}')
        p = b.pool()
        assert p is not None
        assert p.wait_ready(timeout=120), p.stats()
        return b, p
    yield make
    pool_mod.shutdown_all()
    sandbox.reset()


def _call(backend, body, arguments=None, **policy):
    src = ('from sajha.tools.base_mcp_tool import BaseMCPTool\n'
           'class T(BaseMCPTool):\n'
           '    def execute(self, a):\n' + textwrap.indent(textwrap.dedent(body), ' ' * 8))
    policy.setdefault('timeout_seconds', 60)
    res = backend.run({'op': 'python_tool', 'source': src, 'class_name': 'T', 'arguments': arguments or {},
                       'tool_config': {'name': 't'}}, policy_from_config(policy))
    payload = json.loads(res.stdout) if res.stdout.strip().startswith('{') else None
    return res, payload


DIRTY = '''
import ctypes, os, socket, subprocess
for d in ("/work", "/tmp", "/dev/shm"):        # /tmp and /dev/shm only where Landlock is unavailable
    try:
        with open(d + "/leftover", "w") as f:
            f.write("x")
    except OSError:
        pass
subprocess.Popen(["python3", "-c", "import time; time.sleep(600)"], start_new_session=True)
libc = ctypes.CDLL(None)
shm = libc.shmget(0, 4096, 0o1600)          # IPC_PRIVATE, IPC_CREAT | 0600
return {"host": socket.gethostname(), "shm": shm}
'''

INSPECT = """
import os
procs = []
for p in os.listdir('/proc'):
    if p.isdigit() and int(p) not in (1, os.getpid()):
        try:
            procs.append(open('/proc/%s/cmdline' % p).read().replace(chr(0), ' '))
        except OSError:
            pass
files = [d + '/' + n for d in ('/work', '/tmp', '/dev/shm') for n in os.listdir(d)]
shm = open('/proc/sysvipc/shm').read().splitlines()[1:]
print(repr({'procs': procs, 'files': files, 'shm': shm}))
"""


def _docker(*args):
    return subprocess.run([shutil.which('docker') or 'docker', *args], capture_output=True, text=True, timeout=60)


def _inspect(name):
    """What is left in a container, seen from outside the sandbox (the tool's Landlock hides /proc)."""
    import ast
    r = _docker('exec', '-u', '65534:65534', name, 'python3', '-I', '-S', '-c', INSPECT)
    assert r.returncode == 0, r.stderr
    return ast.literal_eval(r.stdout.strip())


def test_reuse_resets_files_processes_and_ipc(docker_backend):
    b, p = docker_backend(size='1', reset='reuse')
    name = list(p._idle)[0].name
    _, first = _call(b, DIRTY)
    assert first and first['ok'], first
    assert first['result']['shm'] >= 0
    assert p.wait_ready(timeout=60), p.stats()
    assert list(p._idle)[0].name == name                         # the same warm container, reset
    left = _inspect(name)
    assert left == {'procs': [], 'files': [], 'shm': []}, left
    _, second = _call(b, 'import socket\nreturn socket.gethostname()')
    assert second['ok'] and second['result'] == first['result']['host']
    st = p.stats()
    assert st['counters']['hits'] == 2 and st['counters']['reset_ok'] >= 1


def test_reset_really_removes_leftovers(docker_backend):
    """Leftovers planted from outside (as if Landlock were unavailable in the container) are removed."""
    b, p = docker_backend(size='1', reset='reuse')
    lease = p.acquire()
    plant = ("import ctypes, subprocess\n"
             "for d in ('/work', '/tmp', '/dev/shm'):\n"
             "    open(d + '/leftover', 'w').write('x')\n"
             "subprocess.Popen(['python3', '-c', 'import time; time.sleep(600)'], start_new_session=True)\n"
             "ctypes.CDLL(None).shmget(0, 4096, 0o1600)\n")
    assert _docker('exec', '-d', '-u', '65534:65534', lease.name, 'python3', '-c', plant).returncode == 0
    time.sleep(1.5)
    dirty = _inspect(lease.name)
    assert len(dirty['files']) == 3 and dirty['shm'] and dirty['procs']
    assert p.reset(lease)
    assert _inspect(lease.name) == {'procs': [], 'files': [], 'shm': []}
    p.release(lease)


def test_reuse_retires_a_container_after_max_uses(docker_backend):
    b, p = docker_backend(size='1', reset='reuse', max_uses='1')
    _, one = _call(b, 'import socket\nreturn socket.gethostname()')
    assert p.wait_ready(timeout=120)
    _, two = _call(b, 'import socket\nreturn socket.gethostname()')
    assert one['ok'] and two['ok'] and one['result'] != two['result']


def test_recreate_gives_every_call_a_fresh_container(docker_backend):
    b, p = docker_backend(size='1', reset='recreate')
    _, one = _call(b, 'import socket\nopen("/work/x", "w").write("1")\nreturn socket.gethostname()')
    assert p.wait_ready(timeout=120), p.stats()
    _, two = _call(b, 'import os, socket\nreturn [socket.gethostname(), os.listdir("/work")]')
    assert one['ok'] and two['ok']
    assert two['result'][0] != one['result'] and two['result'][1] == []
    assert p.stats()['counters']['recycled'] >= 1 and p.stats()['counters']['hits'] == 2


def _labelled(p):
    r = subprocess.run([shutil.which('docker') or 'docker', 'ps', '-a', '--filter',
                        f'label={pool_mod.LABEL}={p.owner}', '--format', '{{.Names}}'],
                       capture_output=True, text=True, timeout=30)
    return [n for n in r.stdout.split() if n]


def test_pool_is_bounded_and_misses_fall_back(docker_backend):
    b, p = docker_backend(size='2', reset='recreate')
    assert len(_labelled(p)) == 2
    a1, a2 = p.acquire(), p.acquire()
    assert a1 and a2 and p.acquire() is None                   # no third container: a miss
    assert len(_labelled(p)) == 2
    # a call that finds no idle container runs in a per-call container (not a pool one)
    _, res = _call(b, 'return 7')
    assert res['ok'] and res['result'] == 7
    st = p.stats()
    assert st['counters']['misses'] >= 2 and st['containers']['busy'] == 2
    p.release(a1)
    p.release(a2)
    assert p.wait_ready(timeout=120)
    assert len(_labelled(p)) == 2
    # a policy that differs from the pool's profile never uses the pool
    hits = p.stats()['counters']['hits']
    _, res = _call(b, 'return 8', memory_mb=128)
    assert res['ok'] and p.stats()['counters']['hits'] == hits
    assert pool_mod.MAX_POOL_SIZE >= 1


def test_health_check_replaces_a_dead_container(docker_backend):
    b, p = docker_backend(size='1', reset='reuse')
    name = list(p._idle)[0].name
    subprocess.run([shutil.which('docker') or 'docker', 'rm', '-f', name], capture_output=True, timeout=30)
    assert p.check_health() == 1
    assert p.wait_ready(timeout=120)
    assert list(p._idle)[0].name != name and p.stats()['counters']['health_failed'] == 1


def test_timed_out_call_discards_its_container(docker_backend):
    b, p = docker_backend(size='1', reset='reuse')
    first = list(p._idle)[0].name
    res, _ = _call(b, 'while True:\n    pass', timeout_seconds=3)
    assert res.timed_out
    deadline = time.time() + 120
    while time.time() < deadline and (not p._idle or list(p._idle)[0].name == first):
        time.sleep(0.5)
    assert p._idle and list(p._idle)[0].name != first
    assert first not in _labelled(p)


def test_egress_proxy_through_a_pooled_container(docker_backend, monkeypatch):
    import http.server
    import threading
    from sajha.sandbox import egress

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', '4')
            self.end_headers()
            self.wfile.write(b'POOL')

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    real = egress._default_resolver
    monkeypatch.setattr(egress, '_default_resolver',
                        lambda h, pt: ['127.0.0.1'] if h == 'allowed.test' else real(h, pt))
    monkeypatch.setenv('SAJHA_SANDBOX_EGRESS_EXEMPT_HOSTS', 'allowed.test')
    monkeypatch.setenv('SAJHA_SANDBOX_EGRESS_MODE', 'proxy')
    try:
        b, p = docker_backend(size='1', reset='reuse')
        body = ('import urllib.request\n'
                'return urllib.request.urlopen("http://allowed.test:%d/" % a["port"], timeout=10).read().decode()')
        _, res = _call(b, body, {'port': port}, network='allowlist', allow_hosts=[f'allowed.test:{port}'])
        assert res and res['ok'] and res['result'] == 'POOL', res
        assert p.stats()['counters']['hits'] == 1
    finally:
        srv.shutdown()
        srv.server_close()
