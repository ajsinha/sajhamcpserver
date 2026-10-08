"""
MCP 2025-11-25 protocol/transport conformance tests for POST/GET/DELETE /mcp.

Uses FastAPI TestClient against the full app.  The full end-to-end check is
the official suite:
    SAJHA_MCP_CONFORMANCE_FIXTURES=true python run_sajha_web.py --port 3092
    npx -y @modelcontextprotocol/conformance@0.1.16 server \
        --url http://127.0.0.1:3092/mcp --spec-version 2025-11-25 --suite all
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

PROTO = '2025-11-25'


@pytest.fixture(scope='module')
def client():
    os.environ['SAJHA_MCP_CONFORMANCE_FIXTURES'] = 'true'
    # These tests exercise registry tools over anonymous MCP calls; anonymous callers get
    # no registry tools by default (mcp.anonymous.tools, see tests/test_hardening.py).
    os.environ['SAJHA_MCP_ANONYMOUS_TOOLS'] = '*'
    from sajha.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    os.environ.pop('SAJHA_MCP_CONFORMANCE_FIXTURES', None)
    os.environ.pop('SAJHA_MCP_ANONYMOUS_TOOLS', None)


def rpc(client, method, params=None, rid=1, headers=None):
    body = {'jsonrpc': '2.0', 'id': rid, 'method': method}
    if params is not None:
        body['params'] = params
    return client.post('/mcp', json=body, headers=headers or {})


def init(client, version=PROTO, capabilities=None):
    return rpc(client, 'initialize', {
        'protocolVersion': version,
        'capabilities': capabilities or {},
        'clientInfo': {'name': 'pytest', 'version': '1'},
    })


# ── initialize / lifecycle ──────────────────────────────────────

class TestLifecycle:
    @pytest.mark.parametrize('version', ['2025-11-25', '2025-06-18', '2025-03-26'])
    def test_supported_version_is_echoed(self, client, version):
        r = init(client, version)
        assert r.status_code == 200
        assert r.json()['result']['protocolVersion'] == version

    def test_unsupported_version_gets_latest(self, client):
        r = init(client, '1999-01-01')
        assert r.json()['result']['protocolVersion'] == PROTO

    def test_initialize_result_shape(self, client):
        res = init(client).json()['result']
        caps = res['capabilities']
        assert {'tools', 'prompts', 'resources', 'logging', 'completions'} <= set(caps)
        # client-only capabilities must not be advertised by the server
        assert 'elicitation' not in caps and 'sampling' not in caps
        assert 'tasks' not in caps
        assert 'websocket' not in caps and 'jsonSchema' not in caps
        assert 'sajha' in caps['experimental']
        assert caps['resources']['subscribe'] is False
        info = res['serverInfo']
        assert info['name'] and info['version'] and info['title']
        assert info['websiteUrl'].startswith('http')
        assert isinstance(res['instructions'], str) and res['instructions']

    def test_session_header_issued(self, client):
        r = init(client)
        assert r.headers.get('mcp-session-id')

    @pytest.mark.parametrize('method', ['notifications/initialized', 'initialized',
                                        'notifications/cancelled', 'notifications/whatever'])
    def test_notifications_get_202_no_body(self, client, method):
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'method': method, 'params': {}})
        assert r.status_code == 202
        assert r.content == b''

    def test_ping_returns_empty_object(self, client):
        r = rpc(client, 'ping', rid='abc')
        assert r.json() == {'jsonrpc': '2.0', 'id': 'abc', 'result': {}}


# ── Streamable HTTP transport ───────────────────────────────────

class TestTransport:
    def test_batch_rejected(self, client):
        r = client.post('/mcp', json=[{'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}])
        assert r.status_code == 400
        body = r.json()
        assert body['error']['code'] == -32600
        assert body['id'] is None

    def test_parse_error(self, client):
        r = client.post('/mcp', content=b'{not json', headers={'Content-Type': 'application/json'})
        assert r.status_code == 400
        assert r.json()['error']['code'] == -32700

    def test_known_session_accepted_unknown_404(self, client):
        sid = init(client).headers['mcp-session-id']
        ok = rpc(client, 'ping', headers={'Mcp-Session-Id': sid, 'MCP-Protocol-Version': PROTO})
        assert ok.status_code == 200
        bad = rpc(client, 'ping', headers={'Mcp-Session-Id': 'does-not-exist'})
        assert bad.status_code == 404

    def test_delete_session(self, client):
        sid = init(client).headers['mcp-session-id']
        assert client.delete('/mcp', headers={'Mcp-Session-Id': sid}).status_code == 204
        assert client.delete('/mcp', headers={'Mcp-Session-Id': sid}).status_code == 404
        assert rpc(client, 'ping', headers={'Mcp-Session-Id': sid}).status_code == 404

    def test_unsupported_protocol_header_400(self, client):
        r = rpc(client, 'ping', headers={'MCP-Protocol-Version': '2020-01-01'})
        assert r.status_code == 400

    def test_get_with_session_is_405(self, client):
        sid = init(client).headers['mcp-session-id']
        r = client.get('/mcp', headers={'Mcp-Session-Id': sid, 'Accept': 'text/event-stream'})
        assert r.status_code == 405

    def test_get_with_unknown_session_is_404(self, client):
        r = client.get('/mcp', headers={'Mcp-Session-Id': 'nope', 'Accept': 'text/event-stream'})
        assert r.status_code == 404

    @pytest.mark.parametrize('origin', ['http://evil.example.com', 'https://attacker.test:8443'])
    def test_foreign_origin_forbidden(self, client, origin):
        assert rpc(client, 'ping', headers={'Origin': origin}).status_code == 403
        assert client.delete('/mcp', headers={'Origin': origin, 'Mcp-Session-Id': 'x'}).status_code == 403
        assert client.get('/mcp', headers={'Origin': origin}).status_code == 403

    @pytest.mark.parametrize('origin', ['http://localhost:5173', 'http://127.0.0.1', 'http://[::1]:3000'])
    def test_local_origin_allowed(self, client, origin):
        assert rpc(client, 'ping', headers={'Origin': origin}).status_code == 200

    def test_validate_origin_config_list(self):
        from sajha.core.mcp_2025_11_25 import validate_origin
        assert validate_origin(None, [])
        assert validate_origin('https://app.example.com', ['https://app.example.com'])
        assert not validate_origin('https://other.example.com', ['https://app.example.com'])
        assert validate_origin('https://other.example.com', ['*'])
        assert not validate_origin('file://localhost', [])

    def test_sse_tool_call_with_progress(self, client):
        sid = init(client).headers['mcp-session-id']
        r = client.post('/mcp', json={
            'jsonrpc': '2.0', 'id': 9, 'method': 'tools/call',
            'params': {'name': 'test_tool_with_progress', 'arguments': {},
                       '_meta': {'progressToken': 'tok'}},
        }, headers={'Mcp-Session-Id': sid, 'Accept': 'application/json, text/event-stream'})
        assert r.status_code == 200
        assert r.headers['content-type'].startswith('text/event-stream')
        msgs = [json.loads(line[5:].strip()) for line in r.text.splitlines()
                if line.startswith('data:') and line[5:].strip()]
        progress = [m for m in msgs if m.get('method') == 'notifications/progress']
        assert [p['params']['progress'] for p in progress] == [0, 50, 100]
        assert msgs[-1]['id'] == 9 and 'result' in msgs[-1]


# ── JSON-RPC result/error shapes ────────────────────────────────

class TestMethods:
    def test_prompts_list_has_id_and_arguments(self, client):
        r = rpc(client, 'prompts/list', rid=42).json()
        assert r['id'] == 42
        prompts = {p['name']: p for p in r['result']['prompts']}
        bug = prompts.get('bug_diagnosis')
        if bug:  # shipped example prompt
            names = {a['name'] for a in bug['arguments']}
            assert {'bug_description', 'error_message', 'code', 'language'} <= names

    def test_prompts_get_has_id(self, client):
        r = rpc(client, 'prompts/get', {'name': 'test_simple_prompt'}, rid=43).json()
        assert r['id'] == 43
        assert r['result']['messages'][0]['content']['text']

    def test_prompts_get_unknown_is_invalid_params(self, client):
        r = rpc(client, 'prompts/get', {'name': 'no_such_prompt'}, rid=44).json()
        assert r['id'] == 44 and r['error']['code'] == -32602

    @pytest.mark.parametrize('method,params', [
        ('tasks/get', {}),
        ('tasks/get', {'taskId': 'missing'}),
        ('tasks/cancel', {'taskId': 'missing'}),
        ('elicitation/respond', {}),
        ('logging/setLevel', {'level': 'loud'}),
    ])
    def test_errors_are_jsonrpc_errors(self, client, method, params):
        r = rpc(client, method, params, rid=5).json()
        assert 'result' not in r
        assert r['error']['code'] == -32602
        assert r['id'] == 5

    def test_logging_set_level_valid(self, client):
        r = rpc(client, 'logging/setLevel', {'level': 'info'}).json()
        assert r['result'] == {}

    def test_unknown_resource_is_32002(self, client):
        r = rpc(client, 'resources/read', {'uri': 'nope://x'}).json()
        assert r['error']['code'] == -32002

    def test_tools_call_unauthenticated_does_not_crash(self, client):
        r = rpc(client, 'tools/call', {'name': 'test_simple_text', 'arguments': {}}).json()
        assert r['result']['content'][0]['type'] == 'text'
        # real (registry) tool path with session=None
        tools = rpc(client, 'tools/list').json()['result']['tools']
        real = next(t for t in tools if not t['name'].startswith(('test_', 'json_schema')))
        r = rpc(client, 'tools/call', {'name': real['name'], 'arguments': {}}).json()
        assert 'result' in r, r  # tool errors are isError results, never -32603

    def test_unknown_tool_is_invalid_params(self, client):
        r = rpc(client, 'tools/call', {'name': 'no_such_tool', 'arguments': {}}).json()
        assert r['error']['code'] == -32602

    def test_tools_list_shape(self, client):
        tools = rpc(client, 'tools/list').json()['result']['tools']
        for t in tools:
            assert isinstance(t['name'], str) and isinstance(t['inputSchema'], dict)
            assert 'icon' not in t
            if 'outputSchema' in t:
                assert t['outputSchema'].get('type') == 'object'
            if 'icons' in t:
                assert all('src' in i for i in t['icons'])
        assert any('outputSchema' in t for t in tools)

    def test_completion_for_prompt(self, client):
        r = rpc(client, 'completion/complete', {
            'ref': {'type': 'ref/prompt', 'name': 'test_prompt_with_arguments'},
            'argument': {'name': 'arg1', 'value': 'x'}}).json()
        assert isinstance(r['result']['completion']['values'], list)


class TestToolFormatting:
    """Structured output and icons, unit-level."""

    class _Tool:
        def __init__(self, schema):
            self.name = 'fake'
            self.output_schema = schema

    def _handler(self):
        from sajha.core.mcp_handler import MCPHandler
        return MCPHandler()

    def test_dict_result_gets_structured_content(self):
        h = self._handler()
        res = h._format_tool_result(self._Tool({'type': 'object'}), {'a': 1})
        assert res['structuredContent'] == {'a': 1}
        assert json.loads(res['content'][0]['text']) == {'a': 1}

    def test_no_schema_no_structured_content(self):
        h = self._handler()
        res = h._format_tool_result(self._Tool({}), {'a': 1})
        assert 'structuredContent' not in res
        assert json.loads(res['content'][0]['text']) == {'a': 1}

    def test_string_and_content_blocks(self):
        h = self._handler()
        assert h._format_tool_result(self._Tool({}), 'hi') == {'content': [{'type': 'text', 'text': 'hi'}]}
        blocks = [{'type': 'text', 'text': 'x'}]
        assert h._format_tool_result(self._Tool({}), blocks) == {'content': blocks}

    def test_icons(self):
        from sajha.core.mcp_2025_11_25 import build_tool_icons
        assert build_tool_icons({'icon': {'type': 'url', 'url': 'https://x/i.png'}}) == [{'src': 'https://x/i.png'}]
        assert build_tool_icons({'icons': [{'src': 'a.png', 'mimeType': 'image/png', 'bogus': 1}]}) == \
            [{'src': 'a.png', 'mimeType': 'image/png'}]
        emoji = build_tool_icons({'icon': {'type': 'emoji', 'emoji': 'X'}})
        assert emoji[0]['src'].startswith('data:image/svg+xml')
        assert build_tool_icons({}) == []

    def test_negotiation(self):
        from sajha.core.mcp_2025_11_25 import negotiate_protocol_version
        assert negotiate_protocol_version('2025-06-18') == '2025-06-18'
        assert negotiate_protocol_version('garbage') == '2025-11-25'
        assert negotiate_protocol_version(None) == '2025-11-25'


class TestWellKnown:
    @pytest.mark.parametrize('path', ['/.well-known/oauth-protected-resource',
                                      '/.well-known/openid-configuration',
                                      '/.well-known/oauth-client/abc'])
    def test_oauth_discovery_not_advertised(self, client, path):
        assert client.get(path).status_code == 404
