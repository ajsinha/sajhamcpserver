# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
MCP Apps extension (io.modelcontextprotocol/ui) on the 2026-07-28 path, and
x-mcp-header annotations on tool inputSchemas (Mcp-Param-{Name} headers).
"""

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from tests.test_mcp_2026_07_28 import modern, result_of  # noqa: E402

EXT = 'io.modelcontextprotocol/ui'
MIME = 'text/html;profile=mcp-app'
VIEW = 'ui://sajha/loan-amortization.html'
LOAN = 'calc_loan_amortization'


@pytest.fixture(scope='module')
def client():
    # anonymous MCP calls to registry tools (default: none, see tests/test_hardening.py)
    os.environ['SAJHA_MCP_ANONYMOUS_TOOLS'] = '*'
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        yield c
    os.environ.pop('SAJHA_MCP_ANONYMOUS_TOOLS', None)


def _tool(client, name, **kw):
    cursor, tools = None, []
    while True:
        params = {'cursor': cursor} if cursor else {}
        res = result_of(modern(client, 'tools/list', params, **kw))
        tools += res['tools']
        cursor = res.get('nextCursor')
        if not cursor:
            break
    return next(t for t in tools if t['name'] == name)


def _all_resources(client):
    cursor, out = None, []
    while True:
        res = result_of(modern(client, 'resources/list', {'cursor': cursor} if cursor else {}))
        out += res['resources']
        cursor = res.get('nextCursor')
        if not cursor:
            return out


class TestMcpApps:
    def test_capability_advertised(self, client):
        caps = result_of(modern(client, 'server/discover'))['capabilities']
        assert caps['extensions'][EXT] == {}

    def test_tool_meta(self, client):
        assert _tool(client, LOAN)['_meta']['ui'] == {'resourceUri': VIEW}

    def test_resource_listed_and_read(self, client):
        listed = [r for r in _all_resources(client) if r['uri'] == VIEW]
        assert listed and listed[0]['mimeType'] == MIME
        res = result_of(modern(client, 'resources/read', {'uri': VIEW}))
        content = res['contents'][0]
        assert content['mimeType'] == MIME and content['uri'] == VIEW
        html = content['text']
        assert 'ui/initialize' in html
        # self-contained: no external scripts, styles or fetches; no innerHTML sinks
        assert not re.search(r'<script[^>]+src=', html)
        assert not re.search(r'<link[^>]+href=', html)
        assert 'fetch(' not in html and not re.search(r'\.innerHTML\s*=', html) and 'eval(' not in html

    def test_unknown_view_not_found(self, client):
        r = modern(client, 'resources/read', {'uri': 'ui://sajha/nope.html'})
        assert r.json()['error']['code'] == -32602     # 2026-07-28 (SEP-2164) resource not found

    def test_tool_result_carries_series(self, client):
        res = result_of(modern(client, 'tools/call', {'name': LOAN, 'arguments': {
            'principal': 300000, 'annual_rate': 6, 'months': 360}}))
        data = res['structuredContent']
        assert len(data['yearly_schedule']) == 30
        assert data['yearly_schedule'][-1]['balance'] == 0
        assert res['content'][0]['type'] == 'text'      # degrades gracefully without Apps

    def test_legacy_path_unchanged(self, client):
        r = client.post('/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {}})
        tools = r.json()['result']['tools']
        loan = next((t for t in tools if t['name'] == LOAN), None)
        assert loan is None or '_meta' not in loan

    def test_disabled(self, client, monkeypatch):
        monkeypatch.setenv('SAJHA_MCP_APPS_ENABLED', 'false')
        caps = result_of(modern(client, 'server/discover'))['capabilities']
        assert EXT not in caps.get('extensions', {})
        assert '_meta' not in _tool(client, LOAN)
        assert not [r for r in _all_resources(client) if r['uri'].startswith('ui://')]

    def test_invalid_ui_meta_ignored(self):
        from sajha.core.mcp_apps import tool_ui_meta
        assert tool_ui_meta({'_meta': {'ui': {'resourceUri': 'https://x/y.html'}}}) is None
        assert tool_ui_meta({'_meta': {'ui': {'resourceUri': 'ui://sajha/missing.html'}}}) is None
        assert tool_ui_meta({'_meta': {'ui': {'resourceUri': VIEW, 'visibility': ['x']}}}) is None
        assert tool_ui_meta({'_meta': {'ui': {'resourceUri': VIEW, 'visibility': ['app']}}}) == \
            {'resourceUri': VIEW, 'visibility': ['app']}


class TestXMcpHeader:
    def test_sanitizer_drops_only_invalid(self):
        from sajha.core.mcp_modern import sanitize_x_mcp_headers
        schema = {'type': 'object', 'x-mcp-header': 'Root', 'properties': {
            'symbol': {'type': 'string', 'x-mcp-header': 'Symbol'},
            'dup': {'type': 'string', 'x-mcp-header': 'symbol'},
            'price': {'type': 'number', 'x-mcp-header': 'Price'},
            'bad': {'type': 'string', 'x-mcp-header': 'has space'},
            'nested': {'type': 'object', 'properties': {'region': {'type': 'string', 'x-mcp-header': 'Region'}}},
            'items': {'type': 'array', 'items': {'type': 'string', 'x-mcp-header': 'Item'}},
        }}
        clean = sanitize_x_mcp_headers(schema, 'demo')
        props = clean['properties']
        assert props['symbol']['x-mcp-header'] == 'Symbol'
        assert props['nested']['properties']['region']['x-mcp-header'] == 'Region'
        for gone in ('dup', 'price', 'bad'):
            assert 'x-mcp-header' not in props[gone]
        assert 'x-mcp-header' not in props['items']['items'] and 'x-mcp-header' not in clean
        assert schema['properties']['price']['x-mcp-header'] == 'Price'      # input untouched

    def test_real_tool_annotated_and_enforced(self, client):
        tool = _tool(client, 'yahoo_get_quote')
        assert tool['inputSchema']['properties']['symbol']['x-mcp-header'] == 'Symbol'
        # body has symbol but no Mcp-Param-Symbol header -> HeaderMismatch before the tool runs
        r = modern(client, 'tools/call', {'name': 'yahoo_get_quote', 'arguments': {'symbol': 'AAPL'}})
        assert r.status_code == 400 and r.json()['error']['code'] == -32020
        r = modern(client, 'tools/call', {'name': 'yahoo_get_quote', 'arguments': {'symbol': 'AAPL'}},
                   headers={'Mcp-Param-Symbol': 'MSFT'})
        assert r.status_code == 400 and r.json()['error']['code'] == -32020
