"""
The ``sajha`` command line (clientsdk/sajhaclient/cli).

Offline tests cover argument typing, profiles (file mode 0600, precedence),
completion and exit codes.  Live tests start a real server (``run_sajha_web.py`` on
a free port, scratch database) once per module and run the commands in-process
against it over HTTP.
"""

import json
import os
import socket
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'clientsdk'))

from sajhaclient.cli import main as cli_main  # noqa: E402
from sajhaclient.cli import profiles  # noqa: E402
from sajhaclient.cli.main import parse_kv, CLIError, build_parser  # noqa: E402
from sajhaclient.cli.render import iter_sse, AskRenderer, Out  # noqa: E402


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv('SAJHA_CONFIG_DIR', str(tmp_path / 'cfg'))
    for k in ('SAJHA_URL', 'SAJHA_API_KEY', 'SAJHA_TOKEN', 'SAJHA_PROFILE', 'SAJHA_TIMEOUT'):
        monkeypatch.delenv(k, raising=False)
    return tmp_path / 'cfg'


def run(capsys, *argv):
    code = cli_main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


# ── offline ──────────────────────────────────────────────────────

def test_parse_kv_types_by_schema():
    schema = {'properties': {'n': {'type': 'integer'}, 's': {'type': 'string'}, 'l': {'type': 'array'}}}
    assert parse_kv(['n=3', 's=42', 'l=[1,2]', 'x=true', 'y=hello'], schema) == \
        {'n': 3, 's': '42', 'l': [1, 2], 'x': True, 'y': 'hello'}
    with pytest.raises(CLIError) as e:
        parse_kv(['n=abc'], schema)
    assert e.value.code == 2
    with pytest.raises(CLIError):
        parse_kv(['novalue'])
    assert parse_kv(['a=1'], strings_only=True) == {'a': '1'}


def test_profiles_file_is_private_and_precedence(cfg, monkeypatch):
    path = profiles.update_profile('default', url='http://a:1', token='tok-123456789', user='admin')
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(path.parent).st_mode) == 0o700
    s = profiles.resolve()
    assert (s.url, s.token, s.sources['url']) == ('http://a:1', 'tok-123456789', 'profile default')
    monkeypatch.setenv('SAJHA_URL', 'http://env:2')
    assert profiles.resolve().url == 'http://env:2'
    assert profiles.resolve(server='http://flag:3').url == 'http://flag:3'
    # a key given on the command line wins over the stored login
    s = profiles.resolve(api_key='sja_x')
    assert s.api_key == 'sja_x' and s.token is None
    assert 'tok-123456789' not in json.dumps(s.describe())


def test_profile_commands_and_config_show(cfg, capsys):
    assert run(capsys, 'profile', 'add', 'prod', 'https://sajha.example.com')[0] == 0
    assert run(capsys, 'profile', 'use', 'prod')[0] == 0
    code, out, _ = run(capsys, 'config', 'show', '--json')
    assert code == 0 and json.loads(out)['url'] == 'https://sajha.example.com'
    assert run(capsys, 'profile', 'use', 'nope')[0] == 5
    code, out, _ = run(capsys, 'profile', 'list')
    assert '* prod' in out.replace('  ', ' ')


def test_usage_and_unreachable_exit_codes(cfg, capsys):
    with pytest.raises(SystemExit) as e:
        cli_main(['no-such-command'])
    assert e.value.code == 2
    assert run(capsys, 'tools')[0] == 2
    code, _, err = run(capsys, '--server', 'http://127.0.0.1:9', 'health')
    assert code == 6 and 'cannot reach' in err


def test_completion_scripts_cover_commands(capsys):
    for shell in ('bash', 'zsh', 'fish'):
        code, out, _ = run(capsys, 'completion', shell)
        assert code == 0
        for word in ('tools', 'ask', 'studio', 'serve', 'federation'):
            assert word in out
    code, out, _ = run(capsys, 'completion', 'bash')
    assert 'complete -F _sajha sajha' in out and 'tools list --names' in out


def test_sse_parser_and_ask_renderer(capsys):
    body = [b'id: 0\n', b'event: shortlist\n', b'data: {"type":"shortlist","seq":0,"tools":[{"name":"t"}]}\n', b'\n',
            b'data: {"type":"tool_call","seq":1,"name":"t","arguments":{"a":1}}\n', b'\n',
            b'data: {"type":"tool_result","seq":2,"name":"t","ok":true,"summary":"fine","latency_ms":3}\n', b'\n',
            b'data: {"type":"answer","seq":3,"text":"42"}\n', b'\n',
            b'data: {"type":"done","seq":4,"result":{"answer":"42"}}\n', b'\n']
    events = list(iter_sse(body))
    assert [e['type'] for e in events] == ['shortlist', 'tool_call', 'tool_result', 'answer', 'done']
    r = AskRenderer(Out(color=False))
    for e in events:
        r.event(e)
    out, err = capsys.readouterr()
    assert '42' in out and '-> t' in err and 'ok' in err
    assert r.result == {'answer': '42'}


def test_serve_without_checkout_is_a_usage_error(cfg, capsys, tmp_path):
    code, _, err = run(capsys, 'serve', '--stdio', '--root', str(tmp_path))
    assert code == 2 and 'not a SAJHA server checkout' in err


# ── live server ──────────────────────────────────────────────────

def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _die_with_parent():
    try:
        import ctypes
        import signal
        ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGKILL)   # PR_SET_PDEATHSIG
    except Exception:
        pass


@pytest.fixture(scope='module')
def live(tmp_path_factory):
    pytest.importorskip('mcp')
    d = tmp_path_factory.mktemp('cli_live')
    port = _free_port()
    env = {**os.environ, 'SAJHA_DB_PATH': str(d / 'cli.db'), 'PYTHONUNBUFFERED': '1'}
    log = open(d / 'server.log', 'wb')
    proc = subprocess.Popen([sys.executable, str(ROOT / 'run_sajha_web.py'), '--port', str(port),
                             '--host', '127.0.0.1'], cwd=str(ROOT), env=env, stdout=log, stderr=log,
                            preexec_fn=_die_with_parent if sys.platform.startswith('linux') else None)
    url = f'http://127.0.0.1:{port}'
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + '/health', timeout=2) as r:
                if r.status == 200:
                    break
        except Exception:
            time.sleep(0.5)
        if proc.poll() is not None:
            pytest.skip('test server failed to start')
    else:
        proc.kill()
        pytest.skip('test server did not become healthy')
    try:
        yield url
    finally:
        _stop(proc, log)


def _stop(proc, log):
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()


@pytest.fixture
def admin(live, cfg, monkeypatch, capsys):
    monkeypatch.setenv('SAJHA_URL', live)
    monkeypatch.setenv('SAJHA_PASSWORD', 'admin123')
    code, out, err = run(capsys, 'login', '-u', 'admin')
    assert code == 0, err
    return live


def test_live_anonymous(live, cfg, monkeypatch, capsys):
    monkeypatch.setenv('SAJHA_URL', live)
    code, out, _ = run(capsys, 'health', '--json')
    assert code == 0 and json.loads(out)['status'] == 'healthy'
    code, out, err = run(capsys, 'tools', 'list')
    assert code == 0 and 'not signed in' in err
    assert run(capsys, 'ask', 'hello')[0] == 3
    assert run(capsys, 'studio', 'delete', 'x')[0] == 3
    monkeypatch.setenv('SAJHA_PASSWORD', 'wrong-password')
    assert run(capsys, 'login', '-u', 'admin')[0] == 3


def test_live_login_and_tools(admin, cfg, capsys):
    path = cfg / 'config.json'
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert json.loads(path.read_text())['profiles']['default']['token']

    code, out, _ = run(capsys, 'tools', 'list', '--filter', '^calc_percentage')
    assert code == 0 and 'calc_percentage_change' in out
    code, out, _ = run(capsys, 'tools', 'list', '--group', '--json', '--filter', '^calc_')
    assert 'calc' in json.loads(out)
    code, out, _ = run(capsys, 'tools', 'list', '--names', '--filter', '^calc_percentage')
    assert out.strip() == 'calc_percentage_change'

    code, out, _ = run(capsys, 'tools', 'show', 'calc_percentage_change')
    assert code == 0 and 'old_value' in out and 'required' in out
    assert run(capsys, 'tools', 'show', 'no_such_tool_xyz')[0] == 5

    code, out, _ = run(capsys, 'tools', 'call', 'calc_percentage_change', '--arg', 'old_value=10',
                       '--arg', 'new_value=15')
    assert code == 0 and json.loads(out)['percentage_change'] == 50.0
    code, out, _ = run(capsys, '-o', 'json', 'tools', 'call', 'calc_percentage_change',
                       '--json', '{"old_value": 1, "new_value": 2}')
    assert code == 0 and json.loads(out)['structuredContent']['percentage_change'] == 100.0
    code, out, _ = run(capsys, 'tools', 'call', 'calc_percentage_change', '--json',
                       '--arg', 'old_value=1', '--arg', 'new_value=4')
    assert code == 0 and json.loads(out)['isError'] is False
    assert run(capsys, 'tools', 'call', 'no_such_tool_xyz')[0] == 5


def test_live_prompts(admin, capsys):
    code, out, _ = run(capsys, 'prompts', 'list')
    assert code == 0 and 'PROMPT' in out
    name = out.splitlines()[1].split()[0]
    code, out, _ = run(capsys, 'prompts', 'list', '--json')
    first = json.loads(out)[0]
    args = [f"{a['name']}=x" for a in first.get('arguments') or [] if a.get('required')]
    code, out, err = run(capsys, 'prompts', 'get', first['name'], *sum((['--arg', a] for a in args), []))
    assert code == 0, err
    assert name


def test_live_ask_streams_steps(admin, capsys):
    code, out, err = run(capsys, 'ask', 'what is the percentage change from 10 to 15')
    if code == 1 and 'not initialized' in err.lower():
        pytest.skip('intelligence service not configured')
    assert code == 0, err
    assert 'shortlist' in err
    code, out, _ = run(capsys, 'ask', '--json', 'what is the percentage change from 10 to 15')
    assert code == 0 and 'answer' in json.loads(out)


def test_live_studio_deploy_and_delete(admin, capsys, tmp_path):
    src = tmp_path / 'cli_test_adder.py'
    src.write_text('from sajha.studio import sajhamcptool\n\n'
                   '@sajhamcptool(description="Add two numbers (CLI test)", category="Test")\n'
                   'def cli_test_adder(a: int, b: int) -> dict:\n'
                   '    return {"sum": a + b}\n')
    code, out, err = run(capsys, 'studio', 'deploy', str(src), '--dry-run')
    assert code == 0, err
    try:
        code, out, err = run(capsys, 'studio', 'deploy', str(src))
        assert code == 0, err
        code, out, err = run(capsys, 'tools', 'call', 'cli_test_adder', '--arg', 'a=2', '--arg', 'b=3')
        assert code == 0 and json.loads(out)['sum'] == 5
    finally:
        code, out, err = run(capsys, 'studio', 'delete', 'cli_test_adder')
    assert code == 0, err
    bad = tmp_path / 'not_a_tool.py'
    bad.write_text('x = 1\n')
    assert run(capsys, 'studio', 'deploy', str(bad))[0] == 1


def test_live_config_and_federation(admin, capsys):
    code, out, _ = run(capsys, 'config', 'show', '--remote')
    assert code in (0, 1)
    code, out, err = run(capsys, 'federation', 'list', '--json')
    assert code in (0, 5), err      # 5: a server without the federation API
    if code == 0:
        assert 'upstreams' in json.loads(out)
    assert run(capsys, 'federation', 'refresh', 'no_such_upstream_xyz')[0] in (5,)


def test_live_workflows(admin, capsys):
    """sajha workflows list|run|runs|show against a workflow saved through the REST API."""
    from sajhaclient.cli import profiles as _p
    tok = _p.resolve().token
    body = json.dumps({'name': 'cli_wf_test', 'steps': [
        {'id': 'pct', 'tool': 'calc_percentage_change',
         'params': {'old_value': '$input.a', 'new_value': '$input.b'}}]}).encode()
    req = urllib.request.Request(admin + '/api/workflows', data=body, method='POST',
                                 headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {tok}'})
    with urllib.request.urlopen(req, timeout=30) as r:
        assert r.status == 200
    code, out, err = run(capsys, 'workflows', 'list')
    assert code == 0 and 'cli_wf_test' in out, err
    code, out, err = run(capsys, 'workflows', 'run', 'cli_wf_test', '--input', 'a=10', '--input', 'b=15',
                         '--wait', '30', '--json')
    assert code == 0, err
    run_rec = json.loads(out)
    assert run_rec['status'] == 'succeeded' and run_rec['output']['pct']['percentage_change'] == 50.0
    code, out, _ = run(capsys, 'workflows', 'runs', 'cli_wf_test')
    assert code == 0 and run_rec['id'] in out
    code, out, _ = run(capsys, 'workflows', 'show', run_rec['id'])
    assert code == 0 and 'pct' in out and 'succeeded' in out
    code, out, _ = run(capsys, 'workflows', 'show', 'cli_wf_test', '--yaml')
    assert code == 0 and 'name: cli_wf_test' in out
    assert run(capsys, 'workflows', 'run', 'cli_wf_test', '--wait', '30')[0] == 1    # missing input: fails
    assert run(capsys, 'workflows', 'show', 'no_such_workflow_xyz')[0] == 5
