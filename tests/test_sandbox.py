"""
The sandbox for user code (sajha/sandbox, docs/architecture/Sandbox.md).

Escape attempts run under every backend installed on this host; a backend that
is not installed is skipped with the reason. Each test asks the sandbox to do
something the server can do, and checks that the sandboxed code cannot.
"""

import json
import os
import socket
import textwrap
import threading
import time
from pathlib import Path

import pytest

from sajha import sandbox
from sajha.sandbox import (SandboxTimeout, PolicyError, get_backend, policy_from_config)
from sajha.sandbox.backends import BACKENDS, PROJECT_ROOT

ALL_BACKENDS = list(BACKENDS)


def _backend(name):
    sandbox.reset()
    b = BACKENDS[name](sandbox.load_settings())
    ok, why = b.available()
    if not ok:
        pytest.skip(f'sandbox backend {name} not available here: {why}')
    return b


@pytest.fixture(params=ALL_BACKENDS)
def backend(request):
    return _backend(request.param)


def _tool(backend, body, arguments=None, **policy):
    """Run a Python tool whose execute(self, a) body is ``body``; return the payload."""
    src = ('from sajha.tools.base_mcp_tool import BaseMCPTool\n'
           'class T(BaseMCPTool):\n'
           '    def execute(self, a):\n' + textwrap.indent(textwrap.dedent(body), ' ' * 8))
    policy.setdefault('timeout_seconds', 30)
    res = backend.run({'op': 'python_tool', 'source': src, 'class_name': 'T',
                       'arguments': arguments or {}, 'tool_config': {'name': 't'}},
                      policy_from_config(policy))
    return res, (json.loads(res.stdout) if res.stdout.strip().startswith('{') else None)


def _attempt(backend, body, arguments=None, **policy):
    """Body sets ``out``; returns out (an 'ERR:...' string means the attempt failed)."""
    code = 'try:\n' + textwrap.indent(textwrap.dedent(body), '    ') + \
           '\nexcept BaseException as e:\n    out = "ERR:" + type(e).__name__ + ":" + str(e)\nreturn out\n'
    res, payload = _tool(backend, code, arguments, **policy)
    assert payload and payload['ok'], (res.stdout, res.stderr, res.runner_error)
    return payload['result']


# ── Normal tools work ──────────────────────────────────────────────────────

def test_python_tool_returns_result(backend):
    res, payload = _tool(backend, 'print("noise on stdout")\nreturn {"sum": a["x"] + a["y"], "name": self.name}',
                         {'x': 2, 'y': 40})
    assert payload == {'ok': True, 'result': {'sum': 42, 'name': 't'}, 'applied': payload['applied']}
    assert 'noise on stdout' in res.stderr  # prints never corrupt the result channel


def test_python_tool_exception_is_reported(backend):
    _, payload = _tool(backend, 'raise ValueError("bad input")')
    assert payload['ok'] is False and payload['error_type'] == 'ValueError' and payload['error'] == 'bad input'


def test_script_runs_with_args(backend):
    res = backend.run({'op': 'exec', 'files': {'s.sh': 'echo "got $1 $2"; echo err >&2; exit 3'},
                       'argv': ['/bin/sh', 's.sh', 'a b', 'c']}, policy_from_config({'timeout_seconds': 20}))
    assert (res.stdout, res.stderr.strip(), res.exit_code) == ('got a b c\n', 'err', 3)


def test_work_dir_is_writable_and_temporary(backend):
    out = _attempt(backend, 'open("scratch.txt", "w").write("x" * 10)\nout = open("scratch.txt").read()')
    assert out == 'x' * 10


# ── Escapes must fail ──────────────────────────────────────────────────────

@pytest.mark.parametrize('path', ['/etc/passwd', '/etc/shadow',
                                  str(PROJECT_ROOT / 'config' / 'application.yml'),
                                  str(PROJECT_ROOT / 'sajha' / 'app.py'),
                                  str(Path.home() / '.bashrc')])
def test_cannot_read_host_files(backend, path):
    if not os.path.exists(path) and path != '/etc/passwd':
        pytest.skip(f'{path} does not exist here')
    out = _attempt(backend, 'out = open(a["p"]).read()[:200]', {'p': path})
    assert out.startswith('ERR:'), f'{backend.name} read {path}: {out!r}'


def test_cannot_list_project_dir(backend):
    out = _attempt(backend, 'import os\nout = os.listdir(a["p"])', {'p': str(PROJECT_ROOT)})
    assert isinstance(out, str) and out.startswith('ERR:')


def test_server_environment_not_inherited(backend, monkeypatch):
    monkeypatch.setenv('SAJHA_JWT_SECRET', 'jwt-secret-must-not-leak')
    monkeypatch.setenv('SOME_API_KEY', 'api-key-must-not-leak')
    out = _attempt(backend, 'import os\nout = dict(os.environ)')
    assert 'SAJHA_JWT_SECRET' not in out and 'SOME_API_KEY' not in out
    assert 'jwt-secret-must-not-leak' not in json.dumps(out)
    # nor through /proc of the server process
    out = _attempt(backend, 'out = open("/proc/%d/environ" % a["pid"], "rb").read().decode(errors="replace")',
                   {'pid': os.getpid()})
    assert 'jwt-secret-must-not-leak' not in out and out.startswith('ERR:')


@pytest.mark.parametrize('target', ['/tmp/zz_sandbox_escape.txt', str(PROJECT_ROOT / 'zz_sandbox_escape.txt')])
def test_cannot_write_outside_work_dir(backend, target):
    try:
        out = _attempt(backend, 'open(a["p"], "w").write("pwned")\nout = "WROTE"', {'p': target})
        assert out.startswith('ERR:')
        assert not os.path.exists(target) or open(target).read() != 'pwned'
    finally:
        if os.path.exists(target) and open(target).read() == 'pwned':
            os.remove(target)


def test_cannot_signal_server(backend):
    out = _attempt(backend, 'import os, signal\nos.kill(a["pid"], signal.SIGTERM)\nout = "SIGNALLED"',
                   {'pid': os.getpid()})
    assert out.startswith('ERR:')


def test_fork_bomb_is_contained(backend):
    body = '''
import os
n = 0
try:
    while n < 5000:
        if os.fork() == 0:
            import time; time.sleep(3); os._exit(0)
        n += 1
except OSError as e:
    pass
out = n
'''
    out = _attempt(backend, body, max_processes=20, timeout_seconds=20)
    assert isinstance(out, int) and out <= 25, out


def _bomb_processes(marker):
    n = 0
    for d in os.listdir('/proc'):
        if d.isdigit():
            try:
                if marker in open(f'/proc/{d}/cmdline', 'rb').read():
                    n += 1
            except OSError:
                pass
    return n


def test_shell_fork_bomb_leaves_nothing_behind(backend):
    """The classic bash fork bomb returns at once (the forks are backgrounded); what
    matters is that the process limit holds and nothing survives the sandbox."""
    marker = ':(){ :|:& };: #zz-sbx-%d' % os.getpid()
    start = time.monotonic()
    backend.run({'op': 'exec', 'argv': ['/bin/bash', '-c', marker]},
                policy_from_config({'timeout_seconds': 5, 'max_processes': 20}))
    assert time.monotonic() - start < 30
    deadline = time.monotonic() + 10
    while _bomb_processes(marker.encode()) and time.monotonic() < deadline:
        time.sleep(0.5)
    assert _bomb_processes(marker.encode()) == 0


def test_memory_blowup_fails(backend):
    _, payload = _tool(backend, 'x = bytearray(2 * 1024 * 1024 * 1024)\nreturn len(x)', memory_mb=256)
    assert payload is None or payload['ok'] is False


def test_infinite_loop_times_out(backend):
    start = time.monotonic()
    res, payload = _tool(backend, 'while True:\n    pass', timeout_seconds=2)
    assert res.timed_out and payload is None
    assert time.monotonic() - start < 20


def test_cpu_limit_stops_busy_loop(backend):
    res, payload = _tool(backend, 'while True:\n    pass', timeout_seconds=30, cpu_seconds=1)
    assert payload is None and not res.timed_out and res.exit_code != 0


def test_huge_output_is_capped(backend):
    res, _ = _tool(backend, 'import sys\nwhile True:\n    sys.stderr.write("x" * 65536)',
                   max_output_bytes=100000, timeout_seconds=20)
    assert res.output_truncated and len(res.stderr) <= 100000


def test_huge_file_is_capped(backend):
    out = _attempt(backend, 'open("big", "wb").write(b"x" * 50 * 1024 * 1024)\nout = "WROTE"', max_file_mb=4)
    assert out.startswith('ERR:')


@pytest.fixture
def local_server():
    """A TCP listener on the host's loopback that records connections."""
    srv = socket.socket()
    srv.bind(('127.0.0.1', 0))
    srv.listen(5)
    hits = []

    def serve():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            hits.append(1)
            c.close()

    threading.Thread(target=serve, daemon=True).start()
    yield srv.getsockname()[1], hits
    srv.close()


def test_network_off_by_default(backend, local_server):
    port, hits = local_server
    out = _attempt(backend, 'import socket\nsocket.create_connection(("127.0.0.1", a["port"]), timeout=3)\nout = "CONNECTED"',
                   {'port': port})
    assert out.startswith('ERR:') and not hits
    out = _attempt(backend, 'import socket\nsocket.create_connection(("1.1.1.1", 53), timeout=3)\nout = "CONNECTED"')
    assert out.startswith('ERR:')


def test_unix_sockets_blocked(backend, tmp_path):
    path = tmp_path / 's.sock'
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(path))
    srv.listen(1)
    try:
        out = _attempt(backend, 'import socket\ns = socket.socket(socket.AF_UNIX)\ns.connect(a["p"])\nout = "CONNECTED"',
                       {'p': str(path)})
        assert out.startswith('ERR:')
    finally:
        srv.close()


@pytest.mark.parametrize('name', ['subprocess', 'bwrap'])
def test_network_allowlist_admits_only_listed_port(name, local_server):
    backend = _backend(name)
    port, hits = local_server
    other = socket.socket()
    other.bind(('127.0.0.1', 0))
    other.listen(1)
    try:
        body = 'import socket\nsocket.create_connection(("127.0.0.1", a["port"]), timeout=3).close()\nout = "CONNECTED"'
        pol = dict(network='allowlist', allow_hosts=[f'127.0.0.1:{port}'])
        assert _attempt(backend, body, {'port': port}, **pol) == 'CONNECTED'
        assert _attempt(backend, body, {'port': other.getsockname()[1]}, **pol).startswith('ERR:')
        assert _attempt(backend, 'import socket\nsocket.getaddrinfo("example.com", 443)\nout = "RESOLVED"',
                        **pol).startswith('ERR:')
    finally:
        other.close()


def test_probe_reports_what_was_applied():
    b = _backend('subprocess')
    p = b.probe(refresh=True)
    assert p['ok'], p
    if os.uname().sysname == 'Linux':
        assert p['applied'].get('rlimits')
    st = sandbox.status(probe=True)
    assert st['active_backend'] == 'subprocess' and st['guarantees']
    assert set(st['backends']) == set(ALL_BACKENDS)


# ── Policy ─────────────────────────────────────────────────────────────────

def test_policy_defaults_and_caps():
    pol = policy_from_config({'timeout_seconds': 99999, 'memory_mb': 128})
    assert pol.timeout_seconds == 300 and pol.memory_mb == 128 and pol.network == 'none'
    assert pol.cpu_seconds == 300  # follows timeout when not set
    with pytest.raises(PolicyError):
        policy_from_config({'network': 'open'})
    with pytest.raises(PolicyError):
        policy_from_config({'network': 'allowlist'})
    with pytest.raises(PolicyError):
        policy_from_config({'env': {'SAJHA_JWT_SECRET': 'x'}})
    with pytest.raises(PolicyError):
        policy_from_config({'env': {'LD_PRELOAD': 'x'}})
    assert policy_from_config({'network': 'allowlist', 'allow_hosts': ['api.x.com', 'b.y:8443']}).allow_ports == [443, 8443]


def test_secrets_only_by_admin_allowlist(monkeypatch):
    monkeypatch.setenv('WEATHER_KEY', 'w-123')
    monkeypatch.setenv('SAJHA_JWT_SECRET', 'jwt')
    pol = policy_from_config({'secrets': ['WEATHER_KEY']})
    with pytest.raises(PolicyError):
        pol.secret_env()
    monkeypatch.setenv('SAJHA_SANDBOX_SECRETS_ALLOWLIST', 'WEATHER_KEY,SAJHA_JWT_SECRET')
    assert pol.secret_env() == {'WEATHER_KEY': 'w-123'}
    with pytest.raises(PolicyError):
        policy_from_config({'secrets': ['SAJHA_JWT_SECRET']}).secret_env()
    b = _backend('subprocess')
    out = _attempt(b, 'import os\nout = os.environ.get("WEATHER_KEY")', secrets=['WEATHER_KEY'])
    assert out == 'w-123'


def test_unavailable_backend_falls_back_unless_strict(monkeypatch):
    monkeypatch.setenv('SAJHA_SANDBOX_DOCKER_IMAGE', 'sajha-no-such-image:never')
    sandbox.reset()
    assert get_backend('docker').name == 'subprocess'
    monkeypatch.setenv('SAJHA_SANDBOX_STRICT', 'true')
    with pytest.raises(sandbox.SandboxUnavailable):
        get_backend('docker')
    sandbox.reset()


# ── Integration: registry, Studio tools, shell ─────────────────────────────

IMPL = PROJECT_ROOT / 'sajha' / 'tools' / 'impl'
SCRIPTS = PROJECT_ROOT / 'config' / 'scripts'


@pytest.fixture
def studio_python_tool():
    """A Studio-generated Python code tool written where the generator writes it."""
    from sajha.studio import CodeAnalyzer, ToolCodeGenerator
    code = textwrap.dedent('''
        from sajha.studio import sajhamcptool

        @sajhamcptool(description="Read a file", category="Test")
        def zz_sbx_reader(path: str) -> dict:
            try:
                return {"content": open(path).read()[:100]}
            except Exception as e:
                return {"error": type(e).__name__}
    ''')
    tool_def = CodeAnalyzer().analyze(code)[0]
    gen = ToolCodeGenerator(tools_dir=str(PROJECT_ROOT / 'config' / 'tools'), impl_dir=str(IMPL))
    cfg = json.loads(gen.generate_tool_json(tool_def, 'zz_sbx_reader'))
    path = IMPL / 'studio_zz_sbx_reader.py'
    path.write_text(gen.generate_python_code(tool_def, 'zz_sbx_reader'))
    yield cfg
    path.unlink(missing_ok=True)


def _registry():
    import logging
    import threading
    from sajha.tools.tools_registry import ToolsRegistry
    reg = ToolsRegistry.__new__(ToolsRegistry)
    reg.tools, reg.tool_configs, reg.tool_errors = {}, {}, {}
    reg._tools_lock, reg.builtin_tools, reg.logger = threading.RLock(), {}, logging.getLogger('t')
    reg._properties_configurator = None
    return reg


def test_studio_python_tool_is_sandboxed_and_never_imported(studio_python_tool):
    import sys
    from sajha.sandbox.tools import SandboxedPythonTool
    assert studio_python_tool['sandbox'] == {'network': 'none'}
    reg = _registry()
    reg.register_tool_from_dict(studio_python_tool)
    tool = reg.tools['zz_sbx_reader']
    assert isinstance(tool, SandboxedPythonTool)
    assert 'sajha.tools.impl.studio_zz_sbx_reader' not in sys.modules
    assert tool.input_schema['properties']['path']['type'] == 'string'
    # The same code in-process would return the server's config; sandboxed it cannot
    out = tool.execute_with_tracking({'path': str(PROJECT_ROOT / 'config' / 'application.yml')})
    assert out == {'error': 'PermissionError'}, out
    assert 'error' in tool.execute({'path': '/etc/passwd'})


def test_studio_python_tool_in_process_when_enforcement_off(studio_python_tool, monkeypatch):
    monkeypatch.setenv('SAJHA_SANDBOX_ENFORCE_FOR_GENERATED_TOOLS', 'false')
    from sajha.sandbox.tools import SandboxedPythonTool
    reg = _registry()
    reg.register_tool_from_dict(studio_python_tool)
    assert not isinstance(reg.tools['zz_sbx_reader'], SandboxedPythonTool)
    monkeypatch.delitem(__import__('sys').modules, 'sajha.tools.impl.studio_zz_sbx_reader', raising=False)


def test_studio_script_tool_is_sandboxed(tmp_path):
    from sajha.studio import ScriptToolConfig, ScriptToolGenerator
    from sajha.sandbox.tools import SandboxedScriptTool
    gen = ScriptToolGenerator(str(tmp_path), str(SCRIPTS), str(tmp_path))
    cfg = ScriptToolConfig(tool_name='zz_sbx_script', description='d', script_type='bash',
                           script_content='echo "arg=$1"; cat "$2" 2>&1 | head -1; echo "jwt=$SAJHA_JWT_SECRET"',
                           timeout_seconds=7)
    tool_cfg = gen.generate_tool_config(cfg)
    assert tool_cfg['sandbox'] == {'network': 'none', 'timeout_seconds': 7}
    gen.save_script_file(cfg)
    try:
        reg = _registry()
        reg.register_tool_from_dict(tool_cfg)
        tool = reg.tools['zz_sbx_script']
        assert isinstance(tool, SandboxedScriptTool) and tool.policy().timeout_seconds == 7
        os.environ['SAJHA_JWT_SECRET'] = 'leak-me'
        try:
            out = tool.execute({'args': ['hi', str(PROJECT_ROOT / 'config' / 'application.yml')]})
        finally:
            os.environ.pop('SAJHA_JWT_SECRET', None)
        assert out['success'] and out['stdout'].startswith('arg=hi\n')
        assert 'Permission denied' in out['stdout'] or 'No such file' in out['stdout']
        assert 'leak-me' not in out['stdout'] and 'jwt=\n' in out['stdout']
    finally:
        for p in SCRIPTS.glob('zz_sbx_script.*'):
            p.unlink()


def test_builtin_tools_stay_in_process():
    from sajha.sandbox.tools import classify
    assert classify({'name': 'wikipedia', 'implementation': 'sajha.tools.impl.wikipedia_tool.WikipediaTool'}) is None
    assert classify({'name': 'x', 'implementation': 'sajha.tools.impl.rest_x.X'}) is None
    assert classify({'name': 'x', 'implementation': 'sajha.tools.impl.studio_x.XTool'}) == 'python'
    assert classify({'name': 'x', 'implementation': 'sajha.tools.impl.x_script_tool.XScriptTool'}) == 'script'
    assert classify({'name': 'x', 'implementation': 'my.mod.X', 'sandbox': {'enabled': True}}) == 'python'


def test_shell_executor_runs_in_sandbox():
    from sajha.core.shell_executor import ShellExecutor
    ex = ShellExecutor({'enabled': True, 'python': {'enabled': True, 'timeout_seconds': 10},
                        'bash': {'enabled': True, 'timeout_seconds': 10}})
    r = ex.execute_python('print(sum(range(10)))')
    assert r.success and r.stdout.strip() == '45' and r.tier.startswith('sandbox:')
    # 'cat' is allowlisted; the sandbox, not the validator, stops it reading the config
    r = ex.execute_bash(f'cat {PROJECT_ROOT}/config/application.yml')
    assert not r.success and 'app:' not in r.stdout
    r = ex.execute_bash('head -1 /etc/passwd')
    assert not r.success and 'root:' not in r.stdout
    assert ex.get_capabilities()['sandbox']
