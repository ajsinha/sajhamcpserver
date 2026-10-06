"""
MCP 2026-07-28 (stateless, "modern") tests for POST/GET/DELETE /mcp.

SAJHA is dual-era: these tests cover the modern path and check that the
legacy (initialize) path still answers alongside it.  End to end:
    SAJHA_MCP_CONFORMANCE_FIXTURES=true python run_server.py --port 3092
    npx -y @modelcontextprotocol/conformance@0.2.0-alpha.12 server \
        --url http://127.0.0.1:3092/mcp --spec-version 2026-07-28 --suite all
"""

import base64
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

V = '2026-07-28'
PV = 'io.modelcontextprotocol/protocolVersion'
CAPS = 'io.modelcontextprotocol/clientCapabilities'
INFO = 'io.modelcontextprotocol/clientInfo'
SERVER_INFO = 'io.modelcontextprotocol/serverInfo'
META = {PV: V, CAPS: {}, INFO: {'name': 'pytest', 'version': '1'}}


@pytest.fixture(scope='module')
def client():
    os.environ['SAJHA_MCP_CONFORMANCE_FIXTURES'] = 'true'
    from sajha.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c
    os.environ.pop('SAJHA_MCP_CONFORMANCE_FIXTURES', None)


def _name_for(method, params):
    key = {'tools/call': 'name', 'prompts/get': 'name', 'resources/read': 'uri'}.get(method)
    return (params or {}).get(key) if key else None


def modern(client, method, params=None, rid=1, headers=None, meta=None, auto_headers=True):
    """POST a 2026-07-28 request with the envelope and the standard headers."""
    params = dict(params or {})
    params['_meta'] = dict(META if meta is None else meta)
    hdrs = {}
    if auto_headers:
        hdrs = {'MCP-Protocol-Version': V, 'Mcp-Method': method,
                'Accept': 'application/json, text/event-stream'}
        name = _name_for(method, params)
        if name is not None:
            hdrs['Mcp-Name'] = name
    hdrs.update(headers or {})
    return client.post('/mcp', json={'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params},
                       headers=hdrs)


def result_of(r):
    assert r.status_code == 200, r.text
    body = r.json()
    assert 'result' in body, body
    return body['result']


# ── era routing ─────────────────────────────────────────────────

class TestEraRouting:
    def test_initialize_still_legacy(self, client):
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}})
        assert r.status_code == 200
        assert r.json()['result']['protocolVersion'] == '2025-11-25'
        assert r.headers.get('mcp-session-id')
        assert 'resultType' not in r.json()['result']

    def test_legacy_request_without_meta_unchanged(self, client):
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        res = result_of(r)
        assert 'resultType' not in res and 'ttlMs' not in res
        assert r.headers.get('mcp-session-id') is None

    def test_modern_request_has_no_session(self, client):
        r = modern(client, 'tools/list', headers={'Mcp-Session-Id': 'ignored-on-modern-path',
                                                  'Last-Event-ID': 'x:1'})
        result_of(r)
        assert r.headers.get('mcp-session-id') is None

    def test_initialize_with_modern_meta_is_method_not_found(self, client):
        r = modern(client, 'initialize')
        assert r.status_code == 404
        assert r.json()['error']['code'] == -32601

    def test_modern_header_without_meta_is_invalid_params(self, client):
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 7, 'method': 'server/discover', 'params': {}},
                        headers={'MCP-Protocol-Version': V, 'Mcp-Method': 'server/discover'})
        assert r.status_code == 400
        assert r.json()['error']['code'] == -32602
        assert r.json()['id'] == 7

    @pytest.mark.parametrize('missing', [PV, CAPS])
    def test_missing_required_meta_field(self, client, missing):
        meta = {k: v for k, v in META.items() if k != missing}
        r = modern(client, 'server/discover', meta=meta)
        assert r.status_code == 400
        assert r.json()['error']['code'] == -32602

    def test_client_info_is_optional(self, client):
        result_of(modern(client, 'server/discover', meta={PV: V, CAPS: {}}))

    def test_modern_notification_is_202(self, client):
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                                      'params': {'_meta': META, 'requestId': 1}},
                        headers={'MCP-Protocol-Version': V, 'Mcp-Method': 'notifications/cancelled'})
        assert r.status_code == 202 and r.content == b''

    def test_parse_error_on_modern_header(self, client):
        r = client.post('/mcp', content=b'{not json', headers={'MCP-Protocol-Version': V,
                                                               'Content-Type': 'application/json'})
        assert r.status_code == 400
        assert r.json()['error']['code'] == -32700


# ── server/discover ─────────────────────────────────────────────

class TestDiscover:
    def test_shape(self, client):
        res = result_of(modern(client, 'server/discover'))
        assert res['resultType'] == 'complete'
        assert res['supportedVersions'][0] == V
        assert '2025-11-25' in res['supportedVersions']
        caps = res['capabilities']
        assert {'tools', 'prompts', 'resources', 'completions'} <= set(caps)
        assert caps['extensions'] == {'io.modelcontextprotocol/tasks': {}, 'io.modelcontextprotocol/ui': {}}
        assert 'tasks' not in caps                        # tasks live under extensions only
        assert caps['logging'] == {}                      # notifications/message on streamed calls
        assert caps['tools']['listChanged'] is True       # delivered on subscriptions/listen
        assert caps['prompts']['listChanged'] is True
        assert caps['resources'] == {'subscribe': True, 'listChanged': True}
        assert 'websocket' not in caps.get('experimental', {}).get('sajha', {})
        assert isinstance(res['instructions'], str) and res['instructions']
        info = res['_meta'][SERVER_INFO]
        assert info['name'] and info['version']
        assert isinstance(res['ttlMs'], int) and res['ttlMs'] >= 0
        assert res['cacheScope'] in ('public', 'private')


# ── headers ─────────────────────────────────────────────────────

class TestHeaders:
    def test_missing_protocol_version_header(self, client):
        r = modern(client, 'tools/list', auto_headers=False, headers={'Mcp-Method': 'tools/list'})
        assert r.status_code == 400
        assert r.json()['error']['code'] == -32020

    def test_protocol_version_header_mismatch(self, client):
        meta = dict(META, **{PV: 'v999'})
        r = modern(client, 'server/discover', meta=meta)
        assert r.status_code == 400 and r.json()['error']['code'] == -32020

    def test_method_header_mismatch(self, client):
        r = modern(client, 'tools/list', headers={'Mcp-Method': 'prompts/list'})
        assert r.status_code == 400 and r.json()['error']['code'] == -32020

    def test_method_header_missing(self, client):
        r = modern(client, 'tools/list', auto_headers=False, headers={'MCP-Protocol-Version': V})
        assert r.status_code == 400 and r.json()['error']['code'] == -32020

    def test_method_header_value_is_case_sensitive(self, client):
        r = modern(client, 'tools/list', headers={'Mcp-Method': 'TOOLS/LIST'})
        assert r.status_code == 400 and r.json()['error']['code'] == -32020

    def test_header_names_case_insensitive(self, client):
        r = modern(client, 'tools/list', auto_headers=False,
                   headers={'mcp-protocol-version': V, 'MCP-METHOD': 'tools/list'})
        result_of(r)

    @pytest.mark.parametrize('method,params', [
        ('tools/call', {'name': 'test_simple_text', 'arguments': {}}),
        ('prompts/get', {'name': 'test_simple_prompt'}),
        ('resources/read', {'uri': 'test://static-text'}),
    ])
    def test_name_header_mismatch_and_missing(self, client, method, params):
        assert modern(client, method, params).status_code == 200
        bad = modern(client, method, params, headers={'Mcp-Name': 'wrong'})
        assert bad.status_code == 400 and bad.json()['error']['code'] == -32020
        hdrs = {'MCP-Protocol-Version': V, 'Mcp-Method': method}
        missing = modern(client, method, params, auto_headers=False, headers=hdrs)
        assert missing.status_code == 400 and missing.json()['error']['code'] == -32020

    def test_name_header_base64_and_whitespace(self, client):
        enc = '=?base64?' + base64.b64encode(b'test_simple_text').decode() + '?='
        result_of(modern(client, 'tools/call', {'name': 'test_simple_text', 'arguments': {}},
                         headers={'Mcp-Name': enc}))
        result_of(modern(client, 'tools/call', {'name': 'test_simple_text', 'arguments': {}},
                         headers={'Mcp-Name': '  test_simple_text  '}))

    def test_custom_param_header(self, client):
        params = {'name': 'test_custom_header', 'arguments': {'region': 'us-west1'}}
        assert modern(client, 'tools/call', params, headers={'Mcp-Param-Region': 'us-west1'}).status_code == 200
        enc = '=?base64?' + base64.b64encode(b'us-west1').decode() + '?='
        assert modern(client, 'tools/call', params, headers={'Mcp-Param-Region': enc}).status_code == 200
        for hdrs in ({}, {'Mcp-Param-Region': 'eu-west1'}, {'Mcp-Param-Region': '=?base64?dXMtd2VzdDE?='}):
            r = modern(client, 'tools/call', params, headers=hdrs)
            assert r.status_code == 400 and r.json()['error']['code'] == -32020, hdrs

    def test_unsupported_version(self, client):
        meta = dict(META, **{PV: '1900-01-01'})
        r = modern(client, 'server/discover', meta=meta, rid=42,
                   headers={'MCP-Protocol-Version': '1900-01-01'})
        assert r.status_code == 400
        err = r.json()['error']
        assert err['code'] == -32022 and r.json()['id'] == 42
        assert err['data']['requested'] == '1900-01-01'
        assert V in err['data']['supported']

    def test_unknown_header_version_without_meta_routes_modern(self, client):
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
                        headers={'MCP-Protocol-Version': '2020-01-01'})
        assert r.status_code == 400


# ── results ─────────────────────────────────────────────────────

class TestResults:
    @pytest.mark.parametrize('method,params', [
        ('tools/list', None), ('prompts/list', None), ('resources/list', None),
        ('resources/templates/list', None), ('resources/read', {'uri': 'test://static-text'}),
        ('tools/call', {'name': 'test_simple_text', 'arguments': {}}),
        ('prompts/get', {'name': 'test_simple_prompt'}),
        ('completion/complete', {'ref': {'type': 'ref/prompt', 'name': 'x'},
                                 'argument': {'name': 'a', 'value': ''}}),
    ])
    def test_result_type_and_server_info(self, client, method, params):
        res = result_of(modern(client, method, params))
        assert res['resultType'] == 'complete'
        assert res['_meta'][SERVER_INFO]['name']

    @pytest.mark.parametrize('method,params', [
        ('tools/list', None), ('prompts/list', None), ('resources/list', None),
        ('resources/templates/list', None), ('resources/read', {'uri': 'test://static-text'}),
    ])
    def test_cache_fields(self, client, method, params):
        res = result_of(modern(client, method, params))
        assert isinstance(res['ttlMs'], int) and res['ttlMs'] >= 0
        assert res['cacheScope'] == 'public'      # no per-user filtering configured

    def test_non_cacheable_results_have_no_cache_fields(self, client):
        res = result_of(modern(client, 'tools/call', {'name': 'test_simple_text', 'arguments': {}}))
        assert 'ttlMs' not in res and 'cacheScope' not in res

    def test_tools_list_is_sorted(self, client):
        tools = result_of(modern(client, 'tools/list'))['tools']
        from sajha.core.mcp_conformance_fixtures import get_conformance_fixtures
        fixture_names = {t['name'] for t in get_conformance_fixtures().tool_definitions('modern')}
        fixtures = [t['name'] for t in tools if t['name'] in fixture_names]
        others = [t['name'] for t in tools[len(fixtures):]]
        assert fixtures == sorted(fixtures)
        assert others == sorted(others)

    def test_modern_only_and_legacy_only_fixtures(self, client):
        modern_names = {t['name'] for t in result_of(modern(client, 'tools/list'))['tools']}
        assert 'test_custom_header' in modern_names
        assert 'test_sampling' not in modern_names        # needs server -> client requests (MRTR, Wave 3)
        legacy = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}).json()
        legacy_names = {t['name'] for t in legacy['result']['tools']}
        assert 'test_custom_header' not in legacy_names and 'test_sampling' in legacy_names

    def test_resource_not_found_is_invalid_params(self, client):
        uri = 'test://nope'
        r = modern(client, 'resources/read', {'uri': uri})
        assert r.status_code == 400
        err = r.json()['error']
        assert err['code'] == -32602 and err['data']['uri'] == uri

    def test_legacy_resource_not_found_still_32002(self, client):
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'resources/read',
                                      'params': {'uri': 'test://nope'}})
        assert r.json()['error']['code'] == -32002

    def test_missing_client_capability(self, client):
        r = modern(client, 'tools/call', {'name': 'test_missing_capability', 'arguments': {}})
        assert r.status_code == 400
        err = r.json()['error']
        assert err['code'] == -32021 and err['data']['requiredCapabilities'] == {'sampling': {}}
        ok = modern(client, 'tools/call', {'name': 'test_missing_capability', 'arguments': {}},
                    meta=dict(META, **{CAPS: {'sampling': {}}}))
        assert result_of(ok)['content'][0]['type'] == 'text'

    def test_logging_tool_never_streams_without_log_level(self, client):
        r = modern(client, 'tools/call', {'name': 'test_logging_tool', 'arguments': {}})
        assert r.headers['content-type'].startswith('application/json')
        assert result_of(r)['resultType'] == 'complete'

    def test_log_level_is_accepted(self, client):
        meta = dict(META, **{'io.modelcontextprotocol/logLevel': 'debug',
                             'traceparent': '00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01'})
        r = modern(client, 'tools/call', {'name': 'test_tool_with_logging', 'arguments': {}}, meta=meta,
                   headers={'Accept': 'application/json'})      # no SSE accepted -> plain JSON
        assert r.headers['content-type'].startswith('application/json')
        assert result_of(r)['content'][0]['text']

    def test_tool_error_is_result(self, client):
        res = result_of(modern(client, 'tools/call', {'name': 'test_error_handling', 'arguments': {}}))
        assert res['isError'] is True

    def test_unknown_tool_is_invalid_params(self, client):
        r = modern(client, 'tools/call', {'name': 'no_such_tool', 'arguments': {}})
        assert r.status_code == 400 and r.json()['error']['code'] == -32602


# ── removed / unknown methods ───────────────────────────────────

class TestMethods:
    @pytest.mark.parametrize('method', [
        'ping', 'logging/setLevel', 'resources/subscribe', 'resources/unsubscribe',
        'tasks/list', 'tasks/result', 'notifications/initialized',
        'api/tools/list', 'tool/schema', 'unknown/method',
    ])
    def test_method_not_found(self, client, method):
        r = modern(client, method, rid=500)
        assert r.status_code == 404
        body = r.json()
        assert body['error']['code'] == -32601 and body['id'] == 500

    def test_batch_rejected(self, client):
        r = client.post('/mcp', json=[{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list',
                                       'params': {'_meta': META}}],
                        headers={'MCP-Protocol-Version': V, 'Mcp-Method': 'tools/list'})
        assert r.status_code == 400 and r.json()['error']['code'] == -32600


# ── GET / DELETE ────────────────────────────────────────────────

class TestGetDelete:
    def test_get_is_405_for_modern_client(self, client):
        r = client.get('/mcp', headers={'MCP-Protocol-Version': V, 'Accept': 'text/event-stream'})
        assert r.status_code == 405
        assert r.headers['allow'] == 'POST'

    def test_delete_is_405_for_modern_client(self, client):
        r = client.delete('/mcp', headers={'MCP-Protocol-Version': V, 'Mcp-Session-Id': 'x'})
        assert r.status_code == 405

    def test_legacy_delete_unchanged(self, client):
        assert client.delete('/mcp').status_code == 400
        assert client.delete('/mcp', headers={'Mcp-Session-Id': 'nope'}).status_code == 404


# ── error code mapping ──────────────────────────────────────────

class TestErrorMapping:
    def test_map_mcp_error(self):
        from sajha.core.mcp_2025_11_25 import MCPError
        from sajha.core.mcp_modern import ModernMCPServer
        m = ModernMCPServer._map_mcp_error
        assert m(MCPError(-32002, 'Resource not found', {'uri': 'u'})).code == -32602
        assert m(MCPError(-32042, 'url elicitation')).code == -32603   # not defined in 2026-07-28
        assert m(MCPError(-32021, 'x')).code == -32021
        assert m(MCPError(-32601, 'x')).status == 404

    def test_decode_header_value(self):
        from sajha.core.mcp_modern import decode_header_value
        assert decode_header_value('=?base64?SGVsbG8=?=') == 'Hello'
        assert decode_header_value('=?base64?SGVsbG8?=') is None        # bad padding
        assert decode_header_value('=?base64?SGVs!!!bG8=?=') is None    # bad alphabet
        assert decode_header_value('=?base64?SGVsbG8=') == '=?base64?SGVsbG8='   # literal


# ═════════════════════════════════════════════════════════════════
# Wave 2: streamed responses, cancellation, subscriptions/listen
# ═════════════════════════════════════════════════════════════════

import asyncio  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402

LOG_LEVEL = 'io.modelcontextprotocol/logLevel'
SUB_ID = 'io.modelcontextprotocol/subscriptionId'
TASKS_EXT = 'io.modelcontextprotocol/tasks'
ALL_CAPS = {'elicitation': {}, 'sampling': {}, 'roots': {}}


def sse_messages(r):
    """JSON-RPC messages from an SSE body (data: lines)."""
    assert r.headers['content-type'].startswith('text/event-stream'), r.headers['content-type']
    out = []
    for line in r.text.splitlines():
        if line.startswith('data:'):
            payload = line[5:].strip()
            if payload:
                out.append(json.loads(payload))
    return out


def _meta(caps=None, **extra):
    m = dict(META, **{CAPS: dict(caps or {})})
    m.update(extra)
    return m


class _FakeTool:
    """A registry tool built on BaseMCPTool, registered for one test."""

    def __init__(self, name, fn, annotations=None, execution=None):
        from sajha.tools.base_mcp_tool import BaseMCPTool

        class T(BaseMCPTool):
            def execute(self, arguments):
                return fn(arguments)

            def get_input_schema(self):
                return self.config['inputSchema']

            def get_output_schema(self):
                return {}

        config = {'name': name, 'description': 'test tool',
                  'inputSchema': {'type': 'object', 'properties': {}}}
        if annotations:
            config['annotations'] = annotations
        if execution:
            config['execution'] = execution
        self.tool = T(config)

    def __enter__(self):
        from sajha.app import mcp_handler
        self.registry = mcp_handler.tools_registry
        self.registry.register_tool(self.tool)
        return self.tool

    def __exit__(self, *exc):
        self.registry.unregister_tool(self.tool.name)


class TestStreaming:
    def test_progress_streamed_over_sse(self, client):
        r = modern(client, 'tools/call', {'name': 'test_tool_with_progress', 'arguments': {}},
                   meta=_meta(progressToken='p-1'))
        msgs = sse_messages(r)
        progress = [m['params'] for m in msgs if m.get('method') == 'notifications/progress']
        assert [p['progress'] for p in progress] == [0, 50, 100]
        assert all(p['progressToken'] == 'p-1' and p['total'] == 100 for p in progress)
        final = msgs[-1]
        assert final['id'] == 1 and final['result']['resultType'] == 'complete'
        assert SERVER_INFO in final['result']['_meta']
        assert all('id' not in m for m in msgs[:-1])     # never a server -> client request

    def test_no_sse_without_progress_token_or_log_level(self, client):
        r = modern(client, 'tools/call', {'name': 'test_tool_with_progress', 'arguments': {}})
        assert r.headers['content-type'].startswith('application/json')
        assert result_of(r)['content'][0]['text']

    def test_json_only_client_gets_json(self, client):
        r = modern(client, 'tools/call', {'name': 'test_tool_with_progress', 'arguments': {}},
                   meta=_meta(progressToken='p-2'), headers={'Accept': 'application/json'})
        assert r.headers['content-type'].startswith('application/json')

    @pytest.mark.parametrize('level,expected', [('debug', 3), ('info', 3), ('warning', 0)])
    def test_log_messages_only_at_requested_level(self, client, level, expected):
        r = modern(client, 'tools/call', {'name': 'test_tool_with_logging', 'arguments': {}},
                   meta=_meta(**{LOG_LEVEL: level}))
        msgs = sse_messages(r)
        logs = [m for m in msgs if m.get('method') == 'notifications/message']
        assert len(logs) == expected
        assert all(m['params']['level'] == 'info' for m in logs)
        assert msgs[-1]['result']['resultType'] == 'complete'

    def test_registry_tool_reports_progress(self, client):
        from sajha.core.mcp_tool_context import report_log, report_progress

        def fn(args):
            report_progress(1, 2, 'half way')
            report_log('debug', 'below the requested level')
            report_log('error', 'something to say')
            report_progress(2, 2)
            return {'ok': True}

        with _FakeTool('zz_test_progress_tool', fn):
            r = modern(client, 'tools/call', {'name': 'zz_test_progress_tool', 'arguments': {}},
                       meta=_meta(progressToken=7, **{LOG_LEVEL: 'warning'}))
        msgs = sse_messages(r)
        progress = [m['params'] for m in msgs if m.get('method') == 'notifications/progress']
        assert progress == [{'progressToken': 7, 'progress': 1, 'total': 2, 'message': 'half way'},
                            {'progressToken': 7, 'progress': 2, 'total': 2}]
        logs = [m['params'] for m in msgs if m.get('method') == 'notifications/message']
        assert logs == [{'level': 'error', 'data': 'something to say'}]
        assert msgs[-1]['result']['content'][0]['type'] == 'text'


class TestCancellation:
    def test_closing_the_stream_cancels_the_call(self):
        from sajha.core.mcp_modern import ModernStream
        started, cancelled, hooks = asyncio.Event(), [], []

        async def producer(emit):
            emit({'jsonrpc': '2.0', 'method': 'notifications/progress', 'params': {}})
            started.set()
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        async def run():
            stream = ModernStream(producer)
            stream.on_close.append(lambda: hooks.append('closed'))
            gen = stream.events()
            first = await gen.__anext__()
            assert json.loads(first['data'])['method'] == 'notifications/progress'
            await started.wait()
            await gen.aclose()                       # what the server does when the client goes away
            await asyncio.sleep(0.05)

        asyncio.run(run())
        assert cancelled == [True] and hooks == ['closed']

    def test_disconnect_cancels_json_call(self):
        from sajha.core.mcp_modern import ModernMCPServer, _CallScope
        server = ModernMCPServer(handler=None)
        flagged, cancelled = [], []

        async def slow():
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        async def gone():
            await asyncio.sleep(0.05)
            return {'type': 'http.disconnect'}

        async def run():
            scope = _CallScope()
            scope.cancel_hooks.append(lambda: flagged.append(True))
            status, payload = await server._until_disconnect(slow(), gone, scope, 9)
            await asyncio.sleep(0.05)
            return status, payload

        status, payload = asyncio.run(run())
        assert status == 499 and payload['id'] == 9 and 'cancelled' in payload['error']['message']
        assert cancelled == [True] and flagged == [True]

    def test_thread_pool_tool_sees_cancellation(self):
        from sajha.core.mcp_tool_context import ModernToolContext, is_cancelled
        ctx = ModernToolContext()
        token = ctx.activate()
        try:
            assert is_cancelled() is False
            ctx.cancel()
            assert is_cancelled() is True
        finally:
            ctx.deactivate(token)


class TestChangeBus:
    def test_filter_coalescing_and_shutdown(self):
        from sajha.core.change_bus import ChangeBus, PROMPTS, RESOURCE_UPDATED, TOOLS

        async def run():
            bus = ChangeBus()
            sub = bus.subscribe({TOOLS, RESOURCE_UPDATED}, ['sajha://tools/catalog'])
            for _ in range(50):
                bus.publish(TOOLS)                       # coalesced while undelivered
            bus.publish(PROMPTS)                         # not subscribed
            bus.publish(RESOURCE_UPDATED, 'sajha://prompts/catalog')   # other URI
            bus.publish(RESOURCE_UPDATED, 'sajha://tools/catalog')
            await asyncio.sleep(0.01)
            got = [(await sub.get()).notification() for _ in range(sub.queue.qsize())]
            bus.shutdown()
            end = await sub.get()
            return got, end

        got, end = asyncio.run(run())
        assert got == [{'jsonrpc': '2.0', 'method': 'notifications/tools/list_changed'},
                       {'jsonrpc': '2.0', 'method': 'notifications/resources/updated',
                        'params': {'uri': 'sajha://tools/catalog'}}]
        assert end is None

    def test_publish_from_another_thread(self):
        import threading
        from sajha.core.change_bus import ChangeBus, TOOLS

        async def run():
            bus = ChangeBus()
            sub = bus.subscribe({TOOLS})
            threading.Thread(target=bus.publish, args=(TOOLS,)).start()
            return await asyncio.wait_for(sub.get(), 2)

        assert asyncio.run(run()).kind == 'tools'

    def test_registry_changes_publish(self, client):
        from sajha.core.change_bus import get_change_bus, TOOLS, RESOURCE_UPDATED

        async def run():
            sub = get_change_bus().subscribe({TOOLS, RESOURCE_UPDATED}, ['sajha://tools/catalog'])
            try:
                with _FakeTool('zz_test_bus_tool', lambda a: 'x'):
                    pass
                await asyncio.sleep(0.05)
                kinds = set()
                while not sub.queue.empty():
                    kinds.add((await sub.get()).kind)
                return kinds
            finally:
                sub.close()

        assert asyncio.run(run()) == {'tools', 'resource_updated'}


def _listen_stream(client, notifications, rid='sub-1', headers=None):
    """Call ModernMCPServer.handle directly for subscriptions/listen (an endless stream)."""
    from sajha.app import mcp_handler
    from sajha.routes.mcp_routes import _modern_server
    body = {'jsonrpc': '2.0', 'id': rid, 'method': 'subscriptions/listen',
            'params': {'_meta': dict(META), 'notifications': notifications}}
    hdrs = {'mcp-protocol-version': V, 'mcp-method': 'subscriptions/listen',
            'accept': 'application/json, text/event-stream'}
    hdrs.update(headers or {})
    return _modern_server(mcp_handler), body, hdrs


class TestSubscriptionsListen:
    def _collect(self, client, notifications, trigger, n, rid='sub-1'):
        from sajha.core.mcp_modern import ModernStream
        server, body, hdrs = _listen_stream(client, notifications, rid)

        async def run():
            stream = await server.handle(body, hdrs, list(hdrs.items()), None)
            assert isinstance(stream, ModernStream)
            gen = stream.events()
            frames = [json.loads((await gen.__anext__())['data'])]
            trigger()
            try:
                while len(frames) < n:
                    frames.append(json.loads((await asyncio.wait_for(gen.__anext__(), 0.5))['data']))
            except asyncio.TimeoutError:
                pass
            await gen.aclose()
            return frames

        return asyncio.run(run())

    def test_ack_first_then_tagged_notifications(self, client):
        from sajha.core.change_bus import get_change_bus
        frames = self._collect(client, {'toolsListChanged': True, 'promptsListChanged': True},
                               lambda: get_change_bus().tools_changed(), 3)
        ack = frames[0]
        assert ack['method'] == 'notifications/subscriptions/acknowledged'
        assert ack['params']['notifications'] == {'toolsListChanged': True, 'promptsListChanged': True}
        assert all(f['params']['_meta'][SUB_ID] == 'sub-1' for f in frames)
        assert [f['method'] for f in frames[1:]] == ['notifications/tools/list_changed']

    def test_filter_is_honored(self, client):
        from sajha.core.change_bus import get_change_bus
        frames = self._collect(client, {'promptsListChanged': True},
                               lambda: get_change_bus().tools_changed(), 3)
        assert [f['method'] for f in frames] == ['notifications/subscriptions/acknowledged']

    def test_resource_subscriptions(self, client):
        from sajha.core.change_bus import get_change_bus
        frames = self._collect(client, {'resourceSubscriptions': ['sajha://prompts/catalog']},
                               lambda: (get_change_bus().tools_changed(), get_change_bus().prompts_changed()), 3,
                               rid=42)
        assert frames[0]['params']['notifications'] == {'resourceSubscriptions': ['sajha://prompts/catalog']}
        assert [(f['method'], f['params'].get('uri')) for f in frames[1:]] == \
            [('notifications/resources/updated', 'sajha://prompts/catalog')]
        assert frames[1]['params']['_meta'][SUB_ID] == 42

    def test_trigger_fixture_and_prompt_registry(self, client):
        from sajha.app import mcp_handler
        reg = mcp_handler.prompts_registry

        def change_prompts():
            ok, msg = reg.create_prompt('zz_test_listen_prompt', {'prompt_template': 'hi {x}',
                                                                  'description': 'test'})
            assert ok, msg
            reg.delete_prompt('zz_test_listen_prompt')

        frames = self._collect(client, {'promptsListChanged': True}, change_prompts, 2)
        assert frames[1]['method'] == 'notifications/prompts/list_changed'

    def test_graceful_end_on_shutdown(self, client):
        from sajha.core.change_bus import get_change_bus
        from sajha.core.mcp_modern import ModernStream
        server, body, hdrs = _listen_stream(client, {'toolsListChanged': True}, rid=5)

        async def run():
            stream = await server.handle(body, hdrs, list(hdrs.items()), None)
            assert isinstance(stream, ModernStream)
            frames = []
            async for ev in stream.events():
                frames.append(json.loads(ev['data']))
                if len(frames) == 1:
                    get_change_bus().shutdown()
            return frames

        frames = asyncio.run(run())
        assert frames[-1]['id'] == 5
        assert frames[-1]['result']['resultType'] == 'complete'
        assert frames[-1]['result']['_meta'][SUB_ID] == 5

    def test_listen_validation(self, client):
        r = modern(client, 'subscriptions/listen', {})
        assert r.status_code == 400 and r.json()['error']['code'] == -32602
        r = modern(client, 'subscriptions/listen', {'notifications': {'toolsListChanged': True}},
                   headers={'Accept': 'application/json'})
        assert r.status_code == 406 and r.json()['error']['code'] == -32600


class TestLegacyPush:
    def test_websocket_advertises_and_receives_list_changed(self, client):
        with client.websocket_connect('/mcp/ws') as ws:
            ws.send_text(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-11-25', 'capabilities': {},
                'clientInfo': {'name': 't', 'version': '1'}}}))
            init = json.loads(ws.receive_text())
            assert init['result']['capabilities']['tools']['listChanged'] is True
            with _FakeTool('zz_test_ws_tool', lambda a: 'x'):
                pass
            methods = {json.loads(ws.receive_text())['method'] for _ in range(2)}
            assert 'notifications/tools/list_changed' in methods

    def test_streamable_http_initialize_keeps_list_changed_false(self, client):
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}})
        assert r.json()['result']['capabilities']['tools']['listChanged'] is False


# ═════════════════════════════════════════════════════════════════
# Wave 3: MRTR, destructive-tool confirmation, tasks extension
# ═════════════════════════════════════════════════════════════════

def call(client, name, arguments=None, caps=None, **extra):
    params = {'name': name, 'arguments': arguments or {}}
    params.update(extra)
    return modern(client, 'tools/call', params, meta=_meta(ALL_CAPS if caps is None else caps))


class TestMRTR:
    def test_round_trip_with_signed_state(self, client):
        r1 = result_of(call(client, 'test_input_required_result_elicitation'))
        assert r1['resultType'] == 'input_required'
        assert r1['inputRequests']['user_name']['method'] == 'elicitation/create'
        assert isinstance(r1['requestState'], str) and '.' in r1['requestState']
        assert 'ttlMs' not in r1
        r2 = result_of(call(client, 'test_input_required_result_elicitation',
                            inputResponses={'user_name': {'action': 'accept', 'content': {'name': 'Alice'}}},
                            requestState=r1['requestState']))
        assert r2['resultType'] == 'complete' and r2['content'][0]['text'] == 'Hello, Alice!'

    def test_tampered_state_rejected(self, client):
        r1 = result_of(call(client, 'test_input_required_result_tampered_state'))
        answer = {'confirm': {'action': 'accept', 'content': {'ok': True}}}
        for bad in (r1['requestState'] + '-TAMPERED', 'x' + r1['requestState'][1:], 'garbage', ''):
            r = call(client, 'test_input_required_result_tampered_state', inputResponses=answer, requestState=bad)
            assert r.status_code == 400 and r.json()['error']['code'] == -32602, bad
        ok = result_of(call(client, 'test_input_required_result_tampered_state', inputResponses=answer,
                            requestState=r1['requestState']))
        assert ok['resultType'] == 'complete'

    def test_state_bound_to_tool_and_arguments(self, client):
        r1 = result_of(call(client, 'test_input_required_result_request_state'))
        answer = {'confirm': {'action': 'accept', 'content': {'ok': True}}}
        other_tool = call(client, 'test_input_required_result_tampered_state', inputResponses=answer,
                          requestState=r1['requestState'])
        assert other_tool.status_code == 400 and 'different request' in other_tool.json()['error']['message']
        other_args = call(client, 'test_input_required_result_request_state', {'x': 1}, inputResponses=answer,
                          requestState=r1['requestState'])
        assert other_args.status_code == 400 and 'arguments' in other_args.json()['error']['message']
        ok = result_of(call(client, 'test_input_required_result_request_state', inputResponses=answer,
                            requestState=r1['requestState']))
        assert 'state-ok' in ok['content'][0]['text']

    def test_expired_state_rejected(self, client, monkeypatch):
        from sajha.core import mcp_mrtr
        token = mcp_mrtr.sign_state(method='tools/call', target='t', arguments={}, user=None,
                                    responses={}, state={}, round_no=1)
        monkeypatch.setattr(mcp_mrtr.time, 'time', lambda: 10 ** 12)
        with pytest.raises(mcp_mrtr.RequestStateError, match='expired'):
            mcp_mrtr.verify_state(token, method='tools/call', target='t', arguments={}, user=None)

    def test_multi_round_accumulates_answers(self, client):
        r1 = result_of(call(client, 'test_input_required_result_multi_round'))
        r2 = result_of(call(client, 'test_input_required_result_multi_round',
                            inputResponses={'step1': {'action': 'accept', 'content': {'name': 'Bo'}}},
                            requestState=r1['requestState']))
        assert list(r2['inputRequests']) == ['step2'] and r2['requestState'] != r1['requestState']
        r3 = result_of(call(client, 'test_input_required_result_multi_round',
                            inputResponses={'step2': {'action': 'accept', 'content': {'color': 'red'}}},
                            requestState=r2['requestState']))
        assert r3['content'][0]['text'] == 'Bo likes red'

    def test_invalid_input_responses(self, client):
        for bad in (None, {'user_name': 12345}, ['x']):
            r = call(client, 'test_input_required_result_elicitation', inputResponses=bad)
            assert r.status_code == 400 and r.json()['error']['code'] == -32602

    def test_missing_capability_for_input(self, client):
        r = call(client, 'test_input_required_result_elicitation', caps={})
        assert r.status_code == 400
        assert r.json()['error']['data']['requiredCapabilities'] == {'elicitation': {}}
        only_sampling = result_of(call(client, 'test_input_required_result_capabilities', caps={'sampling': {}}))
        assert [v['method'] for v in only_sampling['inputRequests'].values()] == ['sampling/createMessage']

    def test_prompts_get_mrtr(self, client):
        p = lambda **kw: modern(client, 'prompts/get', dict({'name': 'test_input_required_result_prompt'}, **kw),
                                meta=_meta(ALL_CAPS))
        r1 = result_of(p())
        assert r1['resultType'] == 'input_required' and 'user_context' in r1['inputRequests']
        r2 = result_of(p(inputResponses={'user_context': {'action': 'accept', 'content': {'context': 'ctx'}}},
                         requestState=r1['requestState']))
        assert r2['resultType'] == 'complete' and 'ctx' in r2['messages'][0]['content']['text']

    def test_never_on_list_methods(self, client):
        for method in ('tools/list', 'prompts/list', 'resources/list'):
            assert result_of(modern(client, method))['resultType'] == 'complete'

    def test_streaming_elicitation_has_no_requests_on_stream(self, client):
        r = modern(client, 'tools/call', {'name': 'test_streaming_elicitation', 'arguments': {}},
                   meta=_meta({'elicitation': {}}, progressToken='s'))
        msgs = sse_messages(r)
        assert all(m.get('method', 'notifications/').startswith('notifications/') for m in msgs)
        assert msgs[-1]['result']['resultType'] == 'input_required'


class TestDestructiveConfirmation:
    def _tool(self):
        return _FakeTool('zz_test_destructive', lambda a: 'deleted', annotations={'destructiveHint': True})

    def test_off_by_default(self, client):
        with self._tool():
            res = result_of(call(client, 'zz_test_destructive'))
        assert res['resultType'] == 'complete' and res['content'][0]['text'] == 'deleted'

    def test_confirmation_flow(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_CONFIRM_DESTRUCTIVE_TOOLS', 'true')
        key = 'sajha_confirm_destructive'
        with self._tool():
            # no elicitation capability -> proceeds as before
            assert result_of(call(client, 'zz_test_destructive', caps={}))['content'][0]['text'] == 'deleted'
            r1 = result_of(call(client, 'zz_test_destructive'))
            req = r1['inputRequests'][key]
            assert req['method'] == 'elicitation/create' and req['params']['mode'] == 'form'
            declined = result_of(call(client, 'zz_test_destructive', inputResponses={key: {'action': 'decline'}},
                                      requestState=r1['requestState']))
            assert declined['isError'] is True
            ok = result_of(call(client, 'zz_test_destructive',
                                inputResponses={key: {'action': 'accept', 'content': {'confirm': True}}},
                                requestState=r1['requestState']))
            assert ok['content'][0]['text'] == 'deleted'

    def test_non_destructive_not_asked(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_CONFIRM_DESTRUCTIVE_TOOLS', 'true')
        with _FakeTool('zz_test_readonly', lambda a: 'read', annotations={'readOnlyHint': True}):
            assert result_of(call(client, 'zz_test_readonly'))['resultType'] == 'complete'


TASK_CAPS = dict(ALL_CAPS, extensions={TASKS_EXT: {}})


def task_req(client, method, task_id, caps=TASK_CAPS, **extra):
    return modern(client, method, dict({'taskId': task_id}, **extra), meta=_meta(caps),
                  headers={'Mcp-Name': task_id})


def wait_status(client, task_id, statuses, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = result_of(task_req(client, 'tasks/get', task_id))
        if res['status'] in statuses:
            return res
        time.sleep(0.05)
    raise AssertionError(f'task {task_id} never reached {statuses}')


class TestTasks:
    def test_create_get_complete(self, client):
        created = result_of(call(client, 'slow_compute', {'seconds': 0.2, 'label': 'a'}, caps=TASK_CAPS))
        assert created['resultType'] == 'task' and created['status'] == 'working'
        assert {'taskId', 'createdAt', 'lastUpdatedAt', 'ttlMs', 'pollIntervalMs'} <= set(created)
        assert 'requestState' not in created and 'task' not in created and 'ttl' not in created
        immediate = result_of(task_req(client, 'tasks/get', created['taskId']))
        assert immediate['taskId'] == created['taskId'] and immediate['resultType'] == 'complete'
        done = wait_status(client, created['taskId'], ('completed',))
        assert done['result']['content'][0]['text'] == 'Computed a in 0.2s'

    def test_sync_without_extension_and_required_rejected(self, client):
        res = result_of(call(client, 'slow_compute', {'seconds': 0}))
        assert res['resultType'] == 'complete' and 'taskId' not in res
        r = call(client, 'failing_job')
        assert r.status_code == 400 and r.json()['error']['code'] == -32021
        assert r.json()['error']['data']['requiredCapabilities'] == {'extensions': {TASKS_EXT: {}}}

    def test_tasks_methods_gated(self, client):
        for method in ('tasks/get', 'tasks/update', 'tasks/cancel'):
            r = task_req(client, method, 'x', caps={})
            assert r.status_code == 400 and r.json()['error']['code'] == -32021

    def test_unknown_task_and_name_header(self, client):
        r = task_req(client, 'tasks/get', 'nope')
        assert r.status_code == 400 and r.json()['error']['code'] == -32602
        r = modern(client, 'tasks/get', {'taskId': 'a'}, meta=_meta(TASK_CAPS), headers={'Mcp-Name': 'b'})
        assert r.json()['error']['code'] == -32020

    def test_cancel(self, client):
        tid = result_of(call(client, 'slow_compute', {'seconds': 30}, caps=TASK_CAPS))['taskId']
        ack = result_of(task_req(client, 'tasks/cancel', tid))
        assert ack['resultType'] == 'complete' and 'status' not in ack
        assert wait_status(client, tid, ('cancelled',))['status'] == 'cancelled'
        assert result_of(task_req(client, 'tasks/cancel', tid))['resultType'] == 'complete'   # idempotent

    def test_tool_error_vs_protocol_error(self, client):
        tid = result_of(call(client, 'failing_job', caps=TASK_CAPS))['taskId']
        done = wait_status(client, tid, ('completed', 'failed'))
        assert done['status'] == 'completed' and done['result']['isError'] is True
        tid = result_of(call(client, 'protocol_error_job', caps=TASK_CAPS))['taskId']
        failed = wait_status(client, tid, ('completed', 'failed'))
        assert failed['status'] == 'failed' and failed['error']['code'] == -32603 and 'result' not in failed

    def test_input_required_and_partial_update(self, client):
        tid = result_of(call(client, 'multi_input', caps=TASK_CAPS))['taskId']
        parked = wait_status(client, tid, ('input_required',))
        assert set(parked['inputRequests']) == {'first', 'second'}
        ack = result_of(task_req(client, 'tasks/update', tid,
                                 inputResponses={'first': {'action': 'accept', 'content': {'name': 'A'}}}))
        assert ack['resultType'] == 'complete' and 'status' not in ack
        still = result_of(task_req(client, 'tasks/get', tid))
        assert still['status'] == 'input_required' and list(still['inputRequests']) == ['second']
        task_req(client, 'tasks/update', tid, inputResponses={'second': {'action': 'accept',
                                                                         'content': {'name': 'B'}}})
        assert wait_status(client, tid, ('completed',))['result']['content'][0]['text'] == 'Got A and B'

    def test_mrtr_then_task(self, client):
        r1 = result_of(call(client, 'test_tool_with_task', caps=TASK_CAPS))
        assert r1['resultType'] == 'input_required' and 'taskId' not in r1
        r2 = result_of(call(client, 'test_tool_with_task', caps=TASK_CAPS,
                            inputResponses={'user_name': {'action': 'accept', 'content': {'name': 'Zed'}}},
                            requestState=r1['requestState']))
        assert r2['resultType'] == 'task' and 'requestState' not in r2
        assert 'Zed' in wait_status(client, r2['taskId'], ('completed',))['result']['content'][0]['text']

    def test_registry_tool_task_support(self, client):
        with _FakeTool('a0_test_task_tool', lambda a: 'from a task', execution={'taskSupport': 'optional'}):
            listed = {t['name']: t for t in result_of(modern(client, 'tools/list'))['tools']}   # page 1
            assert listed['a0_test_task_tool']['execution'] == {'taskSupport': 'optional'}
            created = result_of(call(client, 'a0_test_task_tool', caps=TASK_CAPS))
            assert created['resultType'] == 'task'
            done = wait_status(client, created['taskId'], ('completed',))
            assert done['result']['content'][0]['text'] == 'from a task'
            assert result_of(call(client, 'a0_test_task_tool'))['resultType'] == 'complete'

    def test_tasks_are_scoped_to_their_owner(self):
        from sajha.core.mcp_tasks import TaskNotFound, TaskStore

        async def run():
            store = TaskStore()

            async def runner(task):
                return {'content': []}

            task = store.create('alice', runner)
            await asyncio.sleep(0.01)
            assert store.get(task.task_id, 'alice').status == 'completed'
            with pytest.raises(TaskNotFound):
                store.get(task.task_id, 'bob')
            with pytest.raises(TaskNotFound):
                store.cancel(task.task_id, None)

        asyncio.run(run())
