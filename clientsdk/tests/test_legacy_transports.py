# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Offline tests for the zero-dependency clients (MCPClient, MCPSSEClient,
MCPWebSocketClient) and the transport coalgebra wrappers.
"""

import io
import json
import os
import sys
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sajhaclient  # noqa: E402
from sajhaclient import SajhaConfig  # noqa: E402
from sajhaclient import a2a_client, client as rest_client, mcp_client  # noqa: E402
from sajhaclient.exceptions import SajhaMCPError, SajhaTimeoutError  # noqa: E402
from sajhaclient.mcp_client import (  # noqa: E402
    HTTPTransport, MCPSSEClient, MCPWebSocketClient, SSETransport, WSTransport,
)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Recorder:
    """Stands in for urllib.request.urlopen; records requests, replays a JSON body."""

    def __init__(self, body):
        self.body = body
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        body = self.body(req) if callable(self.body) else self.body
        return _Resp(json.dumps(body).encode())


def _payload(req):
    return json.loads(req.data.decode())


def test_version_is_exported_and_matches_setup():
    setup_py = open(os.path.join(os.path.dirname(__file__), '..', 'setup.py')).read()
    assert '_version.py' in setup_py  # setup.py reads the single source
    assert sajhaclient.SajhaTimeoutError is SajhaTimeoutError


def test_user_agents_derive_from_version(monkeypatch):
    rec = _Recorder({'jsonrpc': '2.0', 'id': 1, 'result': {'tools': []}})
    monkeypatch.setattr(mcp_client.urllib.request, 'urlopen', rec)
    mcp_client.MCPClient(SajhaConfig(base_url='http://x')).list_tools()
    assert rec.requests[-1].get_header('User-agent') == f'sajhaclient-mcp/{sajhaclient.__version__}'

    monkeypatch.setattr(a2a_client.urllib.request, 'urlopen', rec)
    rec.body = {'jsonrpc': '2.0', 'id': 1, 'result': {}}
    a2a_client.A2AClient(SajhaConfig(base_url='http://x'))._rpc('tasks/get', {})
    assert rec.requests[-1].get_header('User-agent') == f'sajhaclient-a2a/{sajhaclient.__version__}'

    for path in ('client.py', 'a2a_client.py', 'mcp_client.py'):
        src = open(os.path.join(os.path.dirname(sajhaclient.__file__), path)).read()
        assert '3.0.0' not in src and '5.3.0' not in src, path


def test_initialize_reports_sdk_version(monkeypatch):
    rec = _Recorder({'jsonrpc': '2.0', 'id': 1, 'result': {'serverInfo': {}, 'capabilities': {}}})
    monkeypatch.setattr(mcp_client.urllib.request, 'urlopen', rec)
    mcp_client.MCPClient(SajhaConfig(base_url='http://x')).initialize()
    assert _payload(rec.requests[-1])['params']['clientInfo']['version'] == sajhaclient.__version__


def test_http_transport_step_tools_call(monkeypatch):
    rec = _Recorder(lambda req: {'jsonrpc': '2.0', 'id': 1, 'result': {'echo': _payload(req)['params']}})
    monkeypatch.setattr(mcp_client.urllib.request, 'urlopen', rec)
    t = HTTPTransport(SajhaConfig(base_url='http://x'))
    # An argument literally called "name" must not collide with the tool name.
    result, state = t.step('tools/call', {'name': 'wiki', 'arguments': {'query': 'q', 'name': 'n'}})
    assert result == {'echo': {'name': 'wiki', 'arguments': {'query': 'q', 'name': 'n'}}}
    assert state['request_count'] == 1
    result, _ = t.step('tools/call', {'name': 'noargs'})
    assert result['echo'] == {'name': 'noargs', 'arguments': {}}


def _connected_sse(monkeypatch, body):
    rec = _Recorder(body)
    monkeypatch.setattr(mcp_client.urllib.request, 'urlopen', rec)
    sse = MCPSSEClient(SajhaConfig(base_url='http://x'))
    sse._message_url = 'http://x/mcp/message'
    sse._connected = True
    return sse, rec


def test_sse_error_args_in_code_message_order(monkeypatch):
    sse, _ = _connected_sse(monkeypatch, {'jsonrpc': '2.0', 'id': 1,
                                          'error': {'code': -32601, 'message': 'Method not found'}})
    with pytest.raises(SajhaMCPError) as ei:
        sse.ping()
    assert ei.value.code == -32601
    assert ei.value.message == 'Method not found'


def test_sse_http_error_is_mcp_error(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 503, 'down', {}, io.BytesIO(b''))
    monkeypatch.setattr(mcp_client.urllib.request, 'urlopen', boom)
    sse = MCPSSEClient(SajhaConfig(base_url='http://x'))
    sse._message_url = 'http://x/m'
    with pytest.raises(SajhaMCPError) as ei:
        sse.ping()
    assert ei.value.code == -32000 and '503' in ei.value.message


def test_sse_transport_step_tools_call(monkeypatch):
    rec = _Recorder(lambda req: {'jsonrpc': '2.0', 'id': 1, 'result': _payload(req)['params']})
    monkeypatch.setattr(mcp_client.urllib.request, 'urlopen', rec)
    t = SSETransport(SajhaConfig(base_url='http://x'))
    t._client._message_url = 'http://x/m'
    result, _ = t.step('tools/call', {'name': 'echo', 'arguments': {'a': 1}})
    assert result == {'name': 'echo', 'arguments': {'a': 1}}


class _FakeWS:
    """Answers each sent request synchronously by feeding the client's response map."""

    def __init__(self, client, reply=True, error=None):
        self.client, self.reply, self.error, self.sent = client, reply, error, []

    def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        if 'id' in msg and self.reply:
            resp = {'jsonrpc': '2.0', 'id': msg['id']}
            if self.error:
                resp['error'] = self.error
            else:
                resp['result'] = {'method': msg['method'], 'params': msg.get('params')}
            self.client._responses[msg['id']] = resp
            self.client._pending[msg['id']].set()


def _ws_transport(**kw):
    t = WSTransport(SajhaConfig(base_url='http://x', timeout=1))
    t._client._ws = _FakeWS(t._client, **kw)
    t._client._connected = True
    return t


def test_ws_transport_step_tools_call_and_generic_method():
    t = _ws_transport()
    result, _ = t.step('tools/call', {'name': 'echo', 'arguments': {'a': 1}})
    assert result == {'method': 'tools/call', 'params': {'name': 'echo', 'arguments': {'a': 1}}}
    # Methods without a dedicated helper used to call the non-existent _send_rpc.
    result, _ = t.step('resources/list', {})
    assert result['method'] == 'resources/list'


def test_ws_timeout_raises_sajha_timeout_error():
    t = _ws_transport(reply=False)
    t._client.config.timeout = 0.05
    with pytest.raises(SajhaTimeoutError):
        t._client.ping()


def test_ws_rpc_error_is_mcp_error():
    t = _ws_transport(error={'code': -32602, 'message': 'bad params'})
    with pytest.raises(SajhaMCPError) as ei:
        t._client.ping()
    assert (ei.value.code, ei.value.message) == (-32602, 'bad params')


def test_rest_client_user_agent(monkeypatch):
    rec = _Recorder({'ok': True})
    monkeypatch.setattr(rest_client.urllib.request, 'urlopen', rec)
    c = rest_client.SajhaClient(SajhaConfig(base_url='http://x'))
    c._request('GET', '/api/health')
    assert rec.requests[-1].get_header('User-agent') == f'sajhaclient/{sajhaclient.__version__}'
