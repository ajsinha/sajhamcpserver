"""
MCP over stdio (sajha/cli/stdio.py): the official SDK client in both eras, the
transport rules (newline-delimited JSON, nothing but protocol on stdout), identity
mapping, and notifications/cancelled.

Each test launches ``run_sajha_web.py --stdio`` as a subprocess against a scratch
database, exactly as a desktop client would.
"""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MODERN = '2026-07-28'
_PROCS: list = []


def _die_with_parent():
    """Linux: the server gets SIGKILL if pytest dies, so no stdio server outlives a run."""
    try:
        import ctypes
        import signal
        ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGKILL)   # PR_SET_PDEATHSIG
    except Exception:
        pass


@pytest.fixture(autouse=True, scope='module')
def _reap():
    yield
    for p in _PROCS:
        if p.poll() is None:
            p.kill()
            try:
                p.wait(timeout=10)
            except Exception:
                pass
META = {'io.modelcontextprotocol/protocolVersion': MODERN,
        'io.modelcontextprotocol/clientCapabilities': {}}


@pytest.fixture(scope='module')
def stdio_env(tmp_path_factory):
    d = tmp_path_factory.mktemp('stdio')
    env = {**os.environ, 'SAJHA_DB_PATH': str(d / 'stdio.db'),
           'SAJHA_MCP_CONFORMANCE_FIXTURES': 'true', 'PYTHONUNBUFFERED': '1'}
    for k in ('SAJHA_API_KEY', 'SAJHA_STDIO_USER'):
        env.pop(k, None)
    return env


class RawServer:
    """A stdio server driven line by line."""

    def __init__(self, env, *args):
        self.proc = subprocess.Popen([sys.executable, str(ROOT / 'run_sajha_web.py'), '--stdio', *args],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     cwd=str(ROOT), env=env,
                                     preexec_fn=_die_with_parent if sys.platform.startswith('linux') else None)
        _PROCS.append(self.proc)
        self.lines: queue.Queue = queue.Queue()
        self.raw: list = []
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            self.raw.append(line)
            self.lines.put(line)
        self.lines.put(None)

    def send(self, message):
        self.proc.stdin.write((json.dumps(message) + '\n').encode())
        self.proc.stdin.flush()

    def recv(self, timeout=60):
        line = self.lines.get(timeout=timeout)
        assert line is not None, 'server closed stdout'
        return json.loads(line)

    def request(self, rid, method, params=None, timeout=60):
        self.send({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params or {}})
        while True:
            msg = self.recv(timeout)
            if msg.get('id') == rid and 'method' not in msg:
                return msg

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            return self.proc.wait(timeout=45)
        except subprocess.TimeoutExpired:
            return None
        finally:
            if self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait(timeout=10)


def _initialize(server):
    r = server.request(1, 'initialize', {'protocolVersion': '2025-11-25', 'capabilities': {'sampling': {}},
                                         'clientInfo': {'name': 'pytest', 'version': '1'}})
    server.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    return r


# ── transport rules, both eras, cancellation (one process) ────────

def test_raw_protocol_both_eras_and_cancellation(stdio_env):
    s = RawServer(stdio_env, '--user', 'admin')
    try:
        # 2026-07-28: server/discover, stateless tools/call
        d = s.request(100, 'server/discover', {'_meta': META})
        assert MODERN in d['result']['supportedVersions']
        assert '2025-11-25' in d['result']['supportedVersions']
        r = s.request(101, 'tools/call', {'_meta': META, 'name': 'calc_percentage_change',
                                          'arguments': {'old_value': 10, 'new_value': 15}})
        assert r['result']['structuredContent']['percentage_change'] == 50.0
        assert r['result']['resultType'] == 'complete'

        # Malformed line -> parse error; batches refused
        s.proc.stdin.write(b'not json\n')
        s.proc.stdin.flush()
        assert s.recv()['error']['code'] == -32700
        s.proc.stdin.write(b'[{"jsonrpc":"2.0","id":5,"method":"ping"}]\n')
        s.proc.stdin.flush()
        assert s.recv()['error']['code'] == -32600

        # Modern streamed call: progress notifications, then the response
        s.send({'jsonrpc': '2.0', 'id': 102, 'method': 'tools/call',
                'params': {'_meta': {**META, 'progressToken': 'p1'}, 'name': 'slow_compute',
                           'arguments': {'seconds': 0.3}}})
        progress, final = [], None
        while final is None:
            m = s.recv()
            if m.get('method') == 'notifications/progress':
                progress.append(m)
            elif m.get('id') == 102:
                final = m
        assert progress and progress[0]['params']['progressToken'] == 'p1'
        assert 'Computed' in final['result']['content'][0]['text']

        # notifications/cancelled: no response for the cancelled request
        s.send({'jsonrpc': '2.0', 'id': 103, 'method': 'tools/call',
                'params': {'_meta': META, 'name': 'slow_compute', 'arguments': {'seconds': 20}}})
        time.sleep(0.5)
        s.send({'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                'params': {'requestId': 103, 'reason': 'test'}})
        after = s.request(104, 'server/discover', {'_meta': META})
        assert after['id'] == 104
        time.sleep(0.5)
        assert not any(json.loads(l).get('id') == 103 for l in s.raw)

        # 2025-11-25 on the same connection: initialize advertises push listChanged
        init = _initialize(s)
        caps = init['result']['capabilities']
        assert init['result']['protocolVersion'] == '2025-11-25'
        assert caps['tools']['listChanged'] is True
        assert 'websocket' not in (caps.get('experimental') or {}).get('sajha', {})
        lst = s.request(2, 'tools/list')
        assert any(t['name'] == 'calc_percentage_change' for t in lst['result']['tools'])

        # legacy cancellation of a call waiting on the client (sampling)
        s.send({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                'params': {'name': 'test_sampling', 'arguments': {'prompt': 'hi'}}})
        req = s.recv()
        assert req['method'] == 'sampling/createMessage'
        s.send({'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': 3}})
        assert s.request(4, 'ping')['result'] == {}
        time.sleep(0.3)
        assert not any(json.loads(l).get('id') == 3 for l in s.raw)

        # list_changed is pushed on stdio (the trigger fixture is a 2026-07-28 tool)
        s.request(6, 'tools/call', {'_meta': META, 'name': 'test_trigger_tool_change', 'arguments': {}})
        deadline = time.time() + 10
        while time.time() < deadline and not any(
                json.loads(l).get('method') == 'notifications/tools/list_changed' for l in s.raw):
            time.sleep(0.1)
        assert any(json.loads(l).get('method') == 'notifications/tools/list_changed' for l in s.raw)
    finally:
        code = s.close()
    # stdout carried only JSON-RPC, one object per line; EOF on stdin -> clean exit
    for line in s.raw:
        assert line.endswith(b'\n')
        msg = json.loads(line)
        assert msg.get('jsonrpc') == '2.0'
    assert code == 0


# ── identity ──────────────────────────────────────────────────────

def test_anonymous_by_default_sees_no_registry_tools(stdio_env):
    s = RawServer(stdio_env)
    try:
        _initialize(s)
        tools = s.request(2, 'tools/list')['result']['tools']
        assert not any(t['name'] == 'calc_percentage_change' for t in tools)
        r = s.request(3, 'tools/call', {'name': 'calc_percentage_change',
                                        'arguments': {'old_value': 1, 'new_value': 2}})
        assert 'error' in r or r['result'].get('isError')
    finally:
        s.close()


def test_unknown_user_or_bad_key_refuses_to_start(stdio_env):
    for args in (('--user', 'no_such_user'), ('--api-key', 'sja_not_a_key')):
        p = subprocess.run([sys.executable, str(ROOT / 'run_sajha_web.py'), '--stdio', *args],
                           input=b'', capture_output=True, cwd=str(ROOT), env=stdio_env, timeout=120)
        assert p.returncode == 2
        assert p.stdout == b''
        assert b'sajha stdio:' in p.stderr


# ── the official SDK client over stdio, both eras ─────────────────

@pytest.mark.parametrize('mode,version', [('legacy', '2025-11-25'), ('auto', MODERN)])
def test_official_sdk_client(stdio_env, mode, version):
    pytest.importorskip('mcp')
    import anyio
    from mcp import Client, StdioServerParameters

    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'run_sajha_web.py'), '--stdio',
                                                                 '--user', 'admin'],
                                   env=stdio_env, cwd=str(ROOT))

    async def run():
        with anyio.fail_after(180):
            await _session()

    async def _session():
        async with Client(params, mode=mode) as c:
            assert c.protocol_version == version
            tools = await c.list_tools()
            assert tools.tools
            r = await c.call_tool('calc_percentage_change', {'old_value': 1, 'new_value': 3})
            assert not r.is_error
            assert r.structured_content['percentage_change'] == 200.0
            prompts = await c.list_prompts()
            assert prompts.prompts
            got = await c.get_prompt('test_simple_prompt', {})
            assert got.messages

    anyio.run(run)
