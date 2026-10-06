"""
MCP 2026-07-28 (stateless, "modern") tests for POST/GET/DELETE /mcp — Wave 1.

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
        assert caps['extensions'] == {}
        assert 'logging' not in caps                     # Wave 1 never sends log notifications
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
        fixtures = [t['name'] for t in tools if t['name'].startswith(('test_', 'json_schema'))]
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
        r = modern(client, 'tools/call', {'name': 'test_tool_with_logging', 'arguments': {}}, meta=meta)
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
        'tasks/get', 'tasks/list', 'tasks/cancel', 'notifications/initialized',
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
