# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The SAJHA Net agent (sajhanet_agent/): its MCP clients (stdio, Streamable HTTP), two agents in an
open-admission net over real HTTP, the conformance suite against an agent over HTTP, and the command
line. Runs without the SAJHA server.
"""

import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sajha.net import conformance, httpsig
from sajha.net.library import self_signed
from sajha.net.models import GossipSettings
from sajha.net.plugins import create
from sajha.net.trust import FirstUseTrust
from sajhanet_agent import Agent, AgentConfig, HttpMCPClient, MCPError, StdioMCPClient
from sajhanet_agent.server import make_server

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ECHO = [sys.executable, os.path.join(HERE, 'echo_mcp_server.py')]


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_stdio_client_lists_and_calls():
    c = StdioMCPClient(ECHO)
    try:
        assert [t['name'] for t in c.list_tools()] == ['echo']
        assert c.call_tool('echo', {'text': 'hi'})['content'][0]['text'] == 'echo: hi'
        with pytest.raises(MCPError):
            c.request('nope/nope', {})
        c.proc.kill()                                   # the server died: the next call restarts it
        c.proc.wait()
        assert c.call_tool('echo', {'text': 'again'})['content'][0]['text'] == 'echo: again'
    finally:
        c.close()


def test_http_client_json_and_sse():
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            msg = json.loads(self.rfile.read(int(self.headers['content-length'])))
            seen.append((msg.get('method'), self.headers.get('mcp-session-id')))
            if 'id' not in msg:
                self.send_response(202)
                self.end_headers()
                return
            if msg['method'] == 'initialize':
                res = {'protocolVersion': '2025-11-25', 'capabilities': {}, 'serverInfo': {'name': 'h', 'version': '1'}}
            elif msg['method'] == 'tools/list':
                res = {'tools': [{'name': 'hello', 'inputSchema': {'type': 'object'}}]}
            else:
                res = {'content': [{'type': 'text', 'text': 'hello there'}]}
            body = json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': res})
            self.send_response(200)
            self.send_header('mcp-session-id', 'sess-1')
            if msg['method'] == 'tools/call':                      # answer as an SSE stream
                data = f'event: message\ndata: {body}\n\n'.encode()
                self.send_header('content-type', 'text/event-stream')
            else:
                data = body.encode()
                self.send_header('content-type', 'application/json')
            self.send_header('content-length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = HttpMCPClient(f'http://127.0.0.1:{srv.server_address[1]}/mcp')
        assert [t['name'] for t in c.list_tools()] == ['hello']
        assert c.call_tool('hello', {})['content'][0]['text'] == 'hello there'
        assert seen[0] == ('initialize', None) and seen[-1] == ('tools/call', 'sess-1')
        c.close()
    finally:
        srv.shutdown()


def _agent(tmp_path, name, port, seeds=(), founder=False):
    cfg = AgentConfig(net='lab-net', instance=name, url=f'http://127.0.0.1:{port}', seeds=list(seeds), founder=founder,
                      data_dir=str(tmp_path / name), require_https=False, mcp_command=' '.join(ECHO),
                      service_calls=True)
    a = Agent(cfg, gossip=GossipSettings(gossip_interval_ms=3600000, ping_timeout_ms=2000,
                                         full_sync_interval_seconds=3600)).start()
    srv = make_server(a, '127.0.0.1', port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return a, srv


def test_two_agents_over_http_and_the_conformance_suite(tmp_path):
    pa, pb = free_port(), free_port()
    b, sb = _agent(tmp_path, 'echo-b', pb, founder=True)
    a, sa = _agent(tmp_path, 'echo-a', pa, seeds=[f'http://127.0.0.1:{pb}'])
    try:
        for _ in range(3):
            a.tick()
            b.tick()
        assert {m['name']: m['state'] for m in a.participant.node.members()} == {'echo-b': 'alive'}
        assert {m['name']: m['record']['kind'] for m in b.participant.node.members()} == {'echo-a': 'agent'}
        assert a.status()['tools'] == ['echo']
        # a restart keeps the identity (the key and certificate in the data directory)
        tp = a.status()['certificate']
        # the suite against agent a, over HTTP, with a self-signed runner (open admission)
        k, c = self_signed('lab-net', 'conformance-t', 'conformance.invalid')
        mem = {}
        rep = conformance.run(f'http://127.0.0.1:{pa}', 'lab-net', connector=create('connector', 'sajha_native'),
                              signer=httpsig.Signer(k, [c]), trust=FirstUseTrust('lab-net', lambda: mem, mem.__setitem__))
        assert not rep.failed(), rep.text()
        assert rep.target['kind'] == 'agent' and rep.status('CAT-03') == 'pass' and rep.status('SIG-06') == 'pass'
        assert rep.status('CALL-04') == 'pass'                     # a key over plain HTTP is refused
        a.stop(leave=False)
        sa.shutdown()
        sa.server_close()
        a2, sa = _agent(tmp_path, 'echo-a', pa, seeds=[f'http://127.0.0.1:{pb}'])
        assert a2.status()['certificate'] == tp
        a2.stop(leave=False)
    finally:
        for s in (sa, sb):
            s.shutdown()
            s.server_close()
        b.stop(leave=False)


def test_command_line_help_and_errors(tmp_path):
    env = dict(os.environ, PYTHONPATH=ROOT)
    out = subprocess.run([sys.executable, '-m', 'sajhanet_agent', '--help'], capture_output=True, text=True, env=env,
                         cwd=ROOT, timeout=60)
    assert out.returncode == 0 and '--mcp-command' in out.stdout and '--seed' in out.stdout
    out = subprocess.run([sys.executable, '-m', 'sajhanet_agent', '--net', 'lab-net', '--instance', 'x-y',
                          '--url', 'https://h:1', '--mcp-command', 'true', '--admission', 'builtin_ca', '--vendor', 'acme',
                          '--data-dir', str(tmp_path / 'd')], capture_output=True, text=True, env=env, cwd=ROOT,
                         timeout=60)
    assert out.returncode == 2 and 'enrollment token' in out.stderr
    out = subprocess.run([sys.executable, '-m', 'sajha.net.conformance', '--target', 'library'], capture_output=True,
                         text=True, env=env, cwd=ROOT, timeout=120)
    assert out.returncode == 0 and '0 failed' in out.stdout
