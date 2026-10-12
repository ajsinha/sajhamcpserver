# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""A container per federated stdio upstream (sajha/federation/container.py; Roadmap L9):
configuration checks, the docker command (network policy, read-only mounts, limits, secrets by
name), the isolation decision and its notices, and a real round trip through docker when it is
available here."""
import asyncio
import json
import os
import shutil
import subprocess
import textwrap
import time
from types import SimpleNamespace

import pytest

from sajha.federation import container as C
from sajha.federation.config import ConfigError

#: a dependency-free MCP server over stdio (2025-11-25 handshake), run inside python:3.13-slim
MINI_SERVER = textwrap.dedent('''
    import json, os, socket, sys
    def send(msg):
        sys.stdout.write(json.dumps(msg) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        rid, method = req.get("id"), req.get("method")
        if rid is None:
            continue
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": req["params"].get("protocolVersion", "2025-11-25"),
                "capabilities": {"tools": {}}, "serverInfo": {"name": "mini", "version": "1"}}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [
                {"name": "probe", "description": "What the container sees.",
                 "inputSchema": {"type": "object", "properties": {}}}]}})
        elif method == "tools/call":
            facts = {"uid": os.getuid(), "secret": os.environ.get("MINI_SECRET", ""),
                     "data": open("/data/hello.txt").read() if os.path.exists("/data/hello.txt") else "",
                     "can_write_data": os.access("/data", os.W_OK), "can_write_root": os.access("/", os.W_OK)}
            try:
                socket.create_connection(("1.1.1.1", 53), timeout=2).close(); facts["network"] = True
            except OSError:
                facts["network"] = False
            send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(facts)}]}})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        else:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "no such method"}})
''')

IMAGE = 'python:3.13-slim'


def _docker_ready():
    exe = shutil.which('docker')
    if not exe:
        return False, 'docker is not installed'
    try:
        r = subprocess.run([exe, 'info'], capture_output=True, timeout=20)
    except Exception as e:
        return False, f'docker info failed: {e}'
    if r.returncode != 0:
        return False, 'docker info failed: the daemon is not reachable'
    r = subprocess.run([exe, 'image', 'inspect', IMAGE], capture_output=True, timeout=20)
    if r.returncode != 0:
        return False, f'image {IMAGE} is not present (docker pull {IMAGE})'
    return True, ''


DOCKER_OK, DOCKER_WHY = _docker_ready()
needs_docker = pytest.mark.skipif(not DOCKER_OK, reason=f'no usable docker here: {DOCKER_WHY}')


def cfg(**kw):
    base = {'id': 'mini', 'command': 'python3', 'args': ['/srv/mini.py'], 'cwd': '', 'isolation': '',
            'container': {}}
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    C._DOCKER_CACHE.clear()
    raised, cleared = [], []
    from sajha import notices
    monkeypatch.setattr(notices, 'raise_notice', lambda nid, **kw: raised.append((nid, kw)))
    monkeypatch.setattr(notices, 'clear_notice', lambda nid, **kw: cleared.append(nid))
    yield SimpleNamespace(raised=raised, cleared=cleared)


# ── configuration ────────────────────────────────────────────────────

def test_validate_rejects_bad_blocks():
    C.validate('stdio', '', {})
    C.validate('stdio', 'container', {'image': 'ghcr.io/acme/mcp:1', 'mounts': ['/srv/data:/data'],
                                      'memory_mb': 256, 'cpus': '0.5', 'user': '1000:1000'})
    for transport, iso, block, match in [
        ('stdio', 'sometimes', {}, 'isolation must be'),
        ('streamable_http', 'container', {}, 'stdio upstreams only'),
        ('stdio', 'none', {'image': 'x'}, 'need isolation: container'),
        ('stdio', '', {'privileged': True}, 'unknown field'),
        ('stdio', '', {'mounts': ['relative:/x']}, 'absolute'),
        ('stdio', '', {'mounts': ['/a/../etc:/x']}, 'plain path'),
        ('stdio', '', {'user': '0'}, 'root'),
        ('stdio', '', {'memory_mb': 0}, 'positive'),
        ('stdio', '', {'network': 'allowlist'}, 'allow_hosts'),
        ('stdio', '', {'network': 'open'}, 'network'),
    ]:
        with pytest.raises(ConfigError, match=match):
            C.validate(transport, iso, block)


def test_build_applies_the_sandbox_policy(monkeypatch, tmp_path):
    monkeypatch.setenv('MINI_SECRET', 'sja_not_on_the_command_line')
    data = tmp_path / 'data'
    data.mkdir()
    launch = C.build(cfg(container={'image': IMAGE, 'mounts': [f'{data}:/data'], 'memory_mb': 999999,
                                    'max_processes': 32}),
                     {'MINI_SECRET': 'sja_not_on_the_command_line'}, name='sajha-fed-mini-1-deadbeef')
    a = launch.argv
    joined = ' '.join(a)
    assert a[1:3] == ['run', '--rm'] and '-i' in a
    assert a[a.index('--network') + 1] == 'none'
    assert '--read-only' in a and 'ALL' == a[a.index('--cap-drop') + 1]
    assert a[a.index('--user') + 1] == '65534:65534'
    assert 'no-new-privileges' in a
    assert f'type=bind,source={data},target=/data,readonly' in a
    # memory capped by sandbox.max (4096 by default)
    from sajha.sandbox import load_settings
    assert a[a.index('--memory') + 1] == f"{load_settings().max['memory_mb']}m"
    assert a[a.index('--pids-limit') + 1] == '32'
    # secrets go by name; the value is only in the docker client's environment
    assert 'sja_not_on_the_command_line' not in joined and ['-e', 'MINI_SECRET'] == a[a.index('MINI_SECRET') - 1:a.index('MINI_SECRET') + 1]
    assert launch.env['MINI_SECRET'] == 'sja_not_on_the_command_line'
    assert a[-2:] == [IMAGE, '/srv/mini.py'] and a[a.index('--entrypoint') + 1] == 'python3'
    assert f'{C.LABEL}=mini' in a


def test_build_allowlist_and_image_default(monkeypatch):
    monkeypatch.setenv('SAJHA_FEDERATION_CONTAINER_IMAGE', 'ghcr.io/acme/default:2')
    monkeypatch.setenv('SAJHA_SANDBOX_EGRESS_MODE', 'direct')    # the egress proxy: tests/test_sandbox_egress.py
    launch = C.build(cfg(container={'network': 'allowlist', 'allow_hosts': ['api.example.com:443']}), {})
    a = launch.argv
    assert a[a.index('--network') + 1] == 'bridge'
    assert 'sajha.allow_host=api.example.com:443' in a
    assert launch.image == 'ghcr.io/acme/default:2'


def test_build_uses_the_sandbox_egress_hook(monkeypatch):
    from sajha.sandbox import BACKENDS
    monkeypatch.setattr(BACKENDS['docker'], 'network_args',
                        lambda self, policy, name: ['--network', 'sajha-egress'], raising=False)
    a = C.build(cfg(container={'network': 'allowlist', 'allow_hosts': ['api.example.com:443']}), {}).argv
    assert a[a.index('--network') + 1] == 'sajha-egress'


@pytest.mark.parametrize('source', ['repo', 'home', 'root', 'docker_sock'])
def test_mounts_never_expose_sajha_or_the_host(source):
    path = {'repo': os.getcwd(), 'home': os.path.expanduser('~'), 'root': '/', 'docker_sock': '/var/run'}[source]
    with pytest.raises(C.IsolationError, match='would expose'):
        C.check_mounts({'mounts': [f'{path}:/x']})


def test_missing_mount_refused(tmp_path):
    with pytest.raises(C.IsolationError, match='does not exist'):
        C.check_mounts({'mounts': [f'{tmp_path}/nope:/x']})


# ── the isolation decision ───────────────────────────────────────────

def test_unset_isolation_without_docker_is_refused(monkeypatch, _fresh):
    monkeypatch.setattr(C, 'docker_available', lambda refresh=False: (False, 'docker is not installed'))
    conn = SimpleNamespace(config=cfg(), isolation=None, container_name=None)
    with pytest.raises(C.IsolationError, match='isolation: none'):
        C.stdio_target(conn, {})
    assert _fresh.raised and _fresh.raised[0][0] == 'federation.stdio_isolation:mini'
    assert _fresh.raised[0][1]['severity'] == 'error'


def test_explicit_container_without_docker_is_refused(monkeypatch):
    monkeypatch.setattr(C, 'docker_available', lambda refresh=False: (False, 'no daemon'))
    with pytest.raises(C.IsolationError, match='isolation: container'):
        C.effective_isolation(cfg(isolation='container'))


def test_explicit_none_runs_unconfined_with_a_warning(monkeypatch, _fresh):
    monkeypatch.setattr(C, 'docker_available', lambda refresh=False: (True, 'docker'))
    conn = SimpleNamespace(config=cfg(isolation='none', command='/usr/bin/env', args=['true']),
                           isolation=None, container_name=None)
    params = C.stdio_target(conn, {'A': '1'})
    assert params.command == '/usr/bin/env' and params.args == ['true'] and params.env == {'A': '1'}
    assert conn.isolation == 'none' and conn.container_name is None
    assert ('federation.stdio_unconfined:mini' in [n for n, _ in _fresh.raised])


def test_unset_isolation_with_docker_is_a_container(monkeypatch, _fresh):
    monkeypatch.setattr(C, 'docker_available', lambda refresh=False: (True, 'docker'))
    monkeypatch.setattr(C, '_remove_orphans_once', lambda: None)
    conn = SimpleNamespace(config=cfg(), isolation=None, container_name=None)
    params = C.stdio_target(conn, {})
    assert conn.isolation == 'container' and conn.container_name.startswith('sajha-fed-mini-')
    assert params.args[0] == 'run' and conn.container_name in params.args
    assert 'federation.stdio_isolation:mini' in _fresh.cleared


def test_orphans_only_from_dead_processes(monkeypatch):
    names = 'sajha-fed-a-999999-0123abcd\nsajha-fed-b-%d-0123abcd\nother\n' % os.getpid()
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=0, stdout=names if 'ps' in argv else '', stderr='')
    monkeypatch.setattr(C.subprocess, 'run', fake_run)
    monkeypatch.setattr(C, '_pid_alive', lambda pid: pid == os.getpid())
    assert C.remove_orphans() == ['sajha-fed-a-999999-0123abcd']
    assert any(c[-3:] == ['rm', '-f', 'sajha-fed-a-999999-0123abcd'] for c in calls)


# ── through docker ───────────────────────────────────────────────────

@needs_docker
def test_round_trip_in_a_container(tmp_path, monkeypatch):
    from mcp import Client
    srv = tmp_path / 'srv'
    srv.mkdir()
    (srv / 'mini.py').write_text(MINI_SERVER)
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'hello.txt').write_text('hello from the host')
    os.chmod(srv, 0o755)
    os.chmod(data, 0o755)
    monkeypatch.setattr(C, '_remove_orphans_once', lambda: None)
    conn = SimpleNamespace(config=cfg(container={'image': IMAGE, 'mounts': [f'{srv}:/srv', f'{data}:/data'],
                                                 'memory_mb': 128}),
                           isolation=None, container_name=None)
    params = C.stdio_target(conn, {'MINI_SECRET': 'sja_value'})
    name = conn.container_name

    async def go():
        async with Client(params, mode='legacy', read_timeout_seconds=60) as c:
            tools = await c.list_tools()
            assert [t.name for t in tools.tools] == ['probe']
            r = await c.call_tool('probe', {})
            return json.loads(r.content[0].text)
    try:
        facts = asyncio.run(asyncio.wait_for(go(), 90))
    finally:
        C.remove(name)
    assert facts['uid'] == 65534
    assert facts['secret'] == 'sja_value'
    assert facts['data'] == 'hello from the host'
    assert facts['can_write_data'] is False and facts['can_write_root'] is False
    assert facts['network'] is False
    r = subprocess.run(['docker', 'ps', '-aq', '--filter', f'name={name}'], capture_output=True, text=True)
    assert r.stdout.strip() == ''


@needs_docker
def test_manager_restarts_the_container(tmp_path, monkeypatch):
    """Through the federation manager: discovery from a container, and a new container after the
    old one is killed (the connection's reconnect loop with backoff)."""
    from sajha.federation.config import FederationSettings, UpstreamConfig
    if 'isolation' not in UpstreamConfig.FIELDS:
        pytest.skip('UpstreamConfig has no isolation field yet (pending edit)')
    from sajha.federation.manager import FederationManager
    from sajha.federation.store import FederationStore
    from tests.test_federation import Registry, wait_for
    monkeypatch.setenv('SAJHA_POLICY_ENABLED', 'false')
    srv = tmp_path / 'srv'
    srv.mkdir()
    (srv / 'mini.py').write_text(MINI_SERVER)
    os.chmod(srv, 0o755)
    settings = FederationSettings(enabled=True, allow_stdio=True, require_approval=False, startup_wait_seconds=60,
                                  default_timeout_seconds=30,
                                  upstreams=[{'id': 'mini', 'transport': 'stdio', 'protocol': 'legacy',
                                              'command': 'python3', 'args': ['/srv/mini.py'],
                                              'container': {'image': IMAGE, 'mounts': [f'{srv}:/srv']}}])
    reg = Registry()
    m = FederationManager(reg, settings, FederationStore(str(tmp_path / 'fed.json')))
    m.start()
    try:
        assert wait_for(lambda: 'mini__probe' in reg.tools, 60), m.status('mini')
        first = m._upstreams['mini'].conn.container_name if hasattr(m._upstreams['mini'], 'conn') else None
        names = subprocess.run(['docker', 'ps', '--filter', f'label={C.LABEL}=mini', '--format', '{{.Names}}'],
                               capture_output=True, text=True).stdout.split()
        assert len(names) == 1 and (first is None or names == [first])
        subprocess.run(['docker', 'kill', names[0]], capture_output=True)

        def restarted():
            now = subprocess.run(['docker', 'ps', '--filter', f'label={C.LABEL}=mini', '--format', '{{.Names}}'],
                                 capture_output=True, text=True).stdout.split()
            return len(now) == 1 and now != names and m.status('mini')['state'] == 'connected'
        assert wait_for(restarted, 60), m.status('mini')
    finally:
        m.stop()
        time.sleep(1)
        left = subprocess.run(['docker', 'ps', '-aq', '--filter', f'label={C.LABEL}=mini'],
                              capture_output=True, text=True).stdout.split()
        if left:
            subprocess.run(['docker', 'rm', '-f', *left], capture_output=True)
    assert not left, 'the container outlived the manager'
