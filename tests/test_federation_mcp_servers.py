# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
The mcpServers file (docs/architecture/Federation.md, "The mcpServers file"): the de-facto standard
``{"mcpServers": {...}}`` JSON becomes federation upstreams, external servers in SAJHA Net by default;
every tracked template in config/mcp_servers/ parses with the real loader; duplicates with
``federation.upstreams``, prefix clashes, reload on change, an OAuth-only server shown as needing
sign-in, and the reserved ``__`` in tool names.
"""

import glob
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sajha.federation.config import FederationSettings, UpstreamConfig
from sajha.federation.manager import FederationManager
from sajha.federation.mcp_servers import McpServersFile, expand, parse
from sajha.federation.store import FederationStore
from tests.test_federation import Registry, Upstream, wait_for

@pytest.fixture(autouse=True)
def _no_leftover_notices():
    yield
    from sajha import notices
    for n in notices.list_notices(state='all'):
        if str(n.get('id', '')).startswith(('federation.', 'tools.reserved_name:')):
            notices.clear_notice(n['id'])


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ECHO = os.path.join(ROOT, 'sajhanet_agent', 'tests', 'echo_mcp_server.py')

OWNER = {"mcpServers": {
    "github": {"url": "https://api.githubcopilot.com/mcp/", "headers": {"Authorization": "Bearer ${GITHUB_PAT}"}},
    "supabase": {"url": "https://mcp.supabase.com/mcp"},
    "notion": {"url": "https://mcp.notion.com/mcp"},
    "context7": {"url": "https://mcp.context7.com/mcp"}}}


def test_expand():
    os.environ['SAJHA_T_X'] = 'v'
    assert expand('a ${SAJHA_T_X} ${SAJHA_T_NONE:dflt} ${SAJHA_T_NONE}.') == 'a v dflt .'


def test_the_owners_example(monkeypatch):
    monkeypatch.setenv('GITHUB_PAT', 'ghp_test')
    p = parse(OWNER)
    assert not p.errors and not p.raw_secrets
    ups = {u['id']: u for u in p.upstreams}
    assert ups['github']['headers'] == {'Authorization': 'Bearer ghp_test'}
    assert {u['transport'] for u in ups.values()} == {'streamable_http'}
    assert [(x['upstream'], x['vendor'], x['prefix']) for x in p.external] == [
        ('github', 'github', 'github'), ('supabase', 'supabase', 'supabase'), ('notion', 'notion', 'notion'),
        ('context7', 'context7', 'context7')]
    for u in p.upstreams:
        UpstreamConfig.from_dict(u, source='file')                     # each is a valid federation upstream
    raw = parse({'mcpServers': {'gh': {'url': 'https://x/mcp', 'headers': {'Authorization': 'Bearer raw'}}}})
    assert raw.raw_secrets == ['gh: Authorization'] and raw.upstreams[0]['headers']['Authorization'] == 'Bearer raw'


def test_keys_stdio_internal_comments_and_errors():
    p = parse({'_comment': 'top', 'mcpServers': {
        '_note': 'ignored',
        'fetch': {'command': 'uvx', 'args': ['mcp-server-fetch'], 'cwd': '/srv', 'vendor': 'mcp_reference',
                  '_why': 'x', 'env': {'A': '1', '_c': 'gone'}},
        'pricing': {'url': 'http://p.internal/mcp', 'external': False},
        'legacy': {'type': 'sse', 'url': 'https://l.example/sse', 'tools': ['get_*'], 'prefix': 'leg'},
        'off': {'url': 'https://o.example/mcp', 'enabled': False},
        'bad': {'url': 'https://b.example/mcp', 'colour': 'red'},
        'worse': {'type': 'carrier-pigeon', 'url': 'x'}}})
    ups = {u['id']: u for u in p.upstreams}
    assert ups['fetch'] == {'id': 'fetch', 'transport': 'stdio', 'command': 'uvx', 'args': ['mcp-server-fetch'],
                            'env': {'A': '1'}, 'cwd': '/srv', 'prefix': 'mcp_reference'}
    assert ups['pricing']['prefix'] == 'pricing' and 'pricing' not in [x['upstream'] for x in p.external]
    assert ups['legacy']['transport'] == 'sse' and ups['legacy']['include_tools'] == ['get_*']
    assert ups['off']['enabled'] is False
    assert set(p.errors) == {'bad', 'worse'} and 'colour' in p.errors['bad']
    assert {x['upstream']: x['prefix'] for x in p.external} == {'fetch': 'mcp_reference', 'legacy': 'leg', 'off': 'off'}


@pytest.mark.parametrize('path', sorted(glob.glob(os.path.join(ROOT, 'config', 'mcp_servers', '*.json.example')))
                         + [os.path.join(ROOT, 'config', 'mcp_servers.json.example')])
def test_every_template_parses_with_the_loader(path, monkeypatch):
    for k in ('GITHUB_PAT', 'VENDOR_MCP_KEY', 'VENDOR_MCP_URL', 'SAJHA_PEER_KEY', 'BRAVE_API_KEY'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv('GITHUB_PAT', 'ghp_t')
    data = json.load(open(path, encoding='utf-8'))
    p = parse(data)
    assert not p.errors, (path, p.errors)
    assert p.upstreams, path
    names = [k for k in data['mcpServers'] if not k.startswith('_')]
    assert [u['id'] for u in p.upstreams] == names
    for u in p.upstreams:
        cfg = UpstreamConfig.from_dict(u, source='file')                 # no drift from federation's rules
        e = data['mcpServers'][u['id']]
        assert cfg.transport == ('stdio' if e.get('command') else 'sse' if e.get('type') == 'sse' else 'streamable_http')
        vendor = e.get('vendor') or u['id']
        assert cfg.effective_prefix == (e.get('prefix') or vendor)
        external = e.get('external', True)
        assert (u['id'] in [x['upstream'] for x in p.external]) == bool(external)
        if e.get('tools'):
            assert cfg.include_tools == list(e['tools'])
        assert cfg.enabled == e.get('enabled', True)
        for h, v in (e.get('headers') or {}).items():
            if '${GITHUB_PAT}' in str(v):
                assert cfg.headers[h] == str(v).replace('${GITHUB_PAT}', 'ghp_t')
    if os.path.basename(path).startswith('04_'):
        ups = {u['id']: u for u in p.upstreams}
        assert ups['github_readonly']['prefix'] == 'github_ro'
        assert ups['vendor_api']['url'] == 'https://mcp.vendor.example/mcp'          # ${NAME:default}
        assert {x['upstream']: x['vendor'] for x in p.external}['github_readonly'] == 'github'


# ── the manager ─────────────────────────────────────────────────────

def _manager(tmp_path, data, upstreams=(), **kw):
    f = tmp_path / 'mcp_servers.json'
    f.write_text(json.dumps(data))
    s = FederationSettings(**{'enabled': False, 'allow_localhost': True, 'allow_stdio': True, 'require_approval': False,
                              'startup_wait_seconds': 10, 'default_timeout_seconds': 10, 'upstreams': list(upstreams),
                              'mcp_servers_file': str(f), **kw})
    reg = Registry()
    m = FederationManager(reg, s, FederationStore(str(tmp_path / 'fed.json')))
    return m, reg, f


def test_duplicates_prefix_clashes_and_reload(tmp_path):
    m, reg, f = _manager(tmp_path, {'mcpServers': {
        'github': {'url': 'https://g.example/mcp'}, 'acme': {'url': 'https://a.example/mcp'},
        'acme2': {'url': 'https://a2.example/mcp', 'vendor': 'acme'}}},
        upstreams=[{'id': 'github', 'url': 'https://yaml.example/mcp'}])
    m.start()
    try:
        assert m.get_config('github').source == 'config' and m.get_config('github').url == 'https://yaml.example/mcp'
        assert 'federation.upstreams' in m.config_errors['github'] and str(f) in m.config_errors['github']
        assert m.get_config('acme').source == 'file'
        assert m.get_config('acme2') is None and 'prefix acme is already used by upstream acme' in m.config_errors['acme2']
        assert [x['upstream'] for x in m.external_servers()] == ['acme']
        from sajha import notices
        n = next(x for x in notices.list_notices(state='all') if x['id'] == 'federation.prefix_clash')
        assert n['severity'] == 'error' and 'acme2' in n['detail'] and '"prefix"' in n['detail']   # never a silent zero
        assert not m.reload_file()                                         # unchanged: nothing re-read
        time.sleep(0.01)
        f.write_text(json.dumps({'mcpServers': {'globex': {'url': 'https://x.example/mcp', 'external': False},
                                                'acme': {'url': 'https://a.example/v2/mcp'}}}))
        os.utime(f, (time.time() + 5, time.time() + 5))
        assert m.reload_file()
        assert m.get_config('globex').source == 'file' and m.get_config('acme').url == 'https://a.example/v2/mcp'
        assert [x['upstream'] for x in m.external_servers()] == ['acme']
        assert 'acme2' not in m.upstream_ids() and 'github' in m.upstream_ids()
        assert 'acme2' not in m.config_errors
        assert not any(x['id'] == 'federation.prefix_clash' for x in notices.list_notices(state='open'))
    finally:
        m.stop()


def test_file_entries_connect_and_tools_are_prefixed(tmp_path, monkeypatch):
    up = Upstream()
    monkeypatch.setenv('T_TOKEN', 'tok-1')
    try:
        m, reg, f = _manager(tmp_path, {'mcpServers': {
            'github': {'url': up.url, 'headers': {'Authorization': 'Bearer ${T_TOKEN}'}, 'tools': ['traced']},
            'echo': {'command': sys.executable, 'args': [ECHO], 'vendor': 'mcp_reference'}}}, enabled=True)
        m.start()
        try:
            assert wait_for(lambda: 'github__traced' in reg.tools and 'mcp_reference__echo' in reg.tools, 20), \
                (sorted(reg.tools), m.config_errors)
            assert set(reg.tools) == {'github__traced', 'mcp_reference__echo'}           # tools: filter
            assert reg.tools['mcp_reference__echo'].execute({'text': 'hi'}) is not None
            assert {x['upstream']: x['prefix'] for x in m.external_servers()} == {'github': 'github',
                                                                                   'echo': 'mcp_reference'}
        finally:
            m.stop()
    finally:
        up.stop()


def test_an_oauth_only_server_needs_sign_in(tmp_path):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Bearer resource_metadata="http://127.0.0.1/.well-known/oauth-protected-resource"')
            self.send_header('content-length', '0')
            self.end_headers()
        do_GET = do_POST
    srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        m, reg, f = _manager(tmp_path, {'mcpServers': {
            'notion': {'url': f'http://127.0.0.1:{srv.server_address[1]}/mcp'}}}, enabled=True, startup_wait_seconds=0)
        m.start()
        try:
            assert wait_for(lambda: m.status('notion')['state'] == 'needs_sign_in', 15), \
                (m.status('notion')['state'], m.status('notion')['last_error'])
            assert 'needs sign-in (not supported yet)' in m.status('notion')['last_error']
            from sajha import notices
            assert any(n['id'] == 'federation.sign_in:notion' for n in notices.list_notices(state='all'))
        finally:
            m.stop()
    finally:
        srv.shutdown()


# ── the reserved "__" ───────────────────────────────────────────────

def test_reserved_separator_in_tool_names():
    from sajha.federation.tool import FederatedTool
    from sajha.tools.base_mcp_tool import BaseMCPTool
    from sajha.tools.naming import reserved_name_problem
    from sajha.tools.tools_registry import ToolsRegistry

    class T(BaseMCPTool):
        def execute(self, arguments):
            return 'x'

        def get_input_schema(self):
            return {'type': 'object'}

        def get_output_schema(self):
            return {}
    reg = ToolsRegistry.__new__(ToolsRegistry)                 # the registry's register_tool, nothing loaded
    import logging
    reg.tools, reg.tool_errors, reg.logger = {}, {}, logging.getLogger('t')
    reg._tools_lock = threading.RLock()
    reg._changed = lambda: None
    with pytest.raises(ValueError, match='reserved'):
        reg.register_tool(T({'name': 'acme__x', 'description': 'd', 'inputSchema': {'type': 'object'}}))
    assert 'acme__x' not in reg.tools and 'reserved' in reg.tool_errors['acme__x']
    from sajha import notices
    assert any(n['id'] == 'tools.reserved_name:acme__x' for n in notices.list_notices(state='all'))
    reg.register_tool(T({'name': 'acme_x', 'description': 'd', 'inputSchema': {'type': 'object'}}))
    reg.register_tool(FederatedTool(None, 'acme', 'x', {'name': 'acme__x', 'inputSchema': {'type': 'object'}}))
    assert {'acme_x', 'acme__x'} <= set(reg.tools)                       # federated tools keep the separator
    assert reserved_name_problem('a__b') and reserved_name_problem('ab') is None
    # creators check it up front
    from sajha.api_import.naming import TOOL_NAME_RE
    from sajha.studio.describe import NAME_RE as DESCRIBE_RE
    from sajha.workflows.model import NAME_RE as WORKFLOW_RE
    for rx in (TOOL_NAME_RE, DESCRIBE_RE, WORKFLOW_RE):
        assert rx.match('acme_tool') and not rx.match('acme__tool')
    from sajha.studio.code_analyzer import CodeAnalyzer
    ok, why = CodeAnalyzer().validate_tool_name('acme__tool', [])
    assert not ok and 'reserved' in why


# ── proxies all the way down: the chain budget across proxied servers ──

def _serve(build):
    """An MCP server (Streamable HTTP on 127.0.0.1) whose tools ``build(srv)`` adds."""
    import socket
    import uvicorn
    from mcp.server.mcpserver import MCPServer
    srv = MCPServer('proxy-test')
    build(srv)
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    uv = uvicorn.Server(uvicorn.Config(srv.streamable_http_app(), host='127.0.0.1', port=port, log_level='warning'))
    threading.Thread(target=uv.run, daemon=True).start()
    assert wait_for(lambda: uv.started, 10)
    return uv, f'http://127.0.0.1:{port}/mcp'


def _meta_dict(ctx):
    meta = ctx.request_context.meta
    if meta is None:
        return {}
    if isinstance(meta, dict):
        return meta
    d = meta.model_dump(by_alias=True) if hasattr(meta, 'model_dump') else {}
    d.update(getattr(meta, 'model_extra', None) or {})
    return d


def test_a_cycle_of_proxies_is_refused_at_the_limit(tmp_path, monkeypatch):
    """A proxies B and B proxies A: A's pb__pong runs B's pong, which calls A's pa__ping... Each SAJHA
    runs an incoming call with the depth it carries (as MCPHandler does), so the chain stops at
    tools.max_call_depth with a clear error instead of recursing."""
    pytest.importorskip('mcp.server.mcpserver')
    from mcp.server.mcpserver import Context
    from sajha.core import inner_calls
    monkeypatch.setattr(inner_calls, 'max_depth', lambda: 4)
    managers = {}
    seen = []

    def via(target, tool):
        def build(srv):
            @srv.tool(name=tool.split('__')[-1], description=f'calls {tool} on the other side')
            def hop(ctx: Context, q: str = '') -> str:
                depth = inner_calls.proxy_depth_of(_meta_dict(ctx))
                seen.append(depth)
                with inner_calls.proxied_entered(depth):
                    t = managers[target].registry.tools[tool]
                    try:
                        out = t.execute({'q': q})
                    except Exception as e:
                        return f'refused: {e}'
                return str(out)
        return build
    uv_a, url_a = _serve(via('b', 'pa__ping'))       # "A": its pong calls B's proxy of A (pa__ping)
    uv_b, url_b = _serve(via('a', 'pb__pong'))       # "B": its ping calls A's proxy of B (pb__pong)
    try:
        for name, uid, url in (('a', 'pb', url_b), ('b', 'pa', url_a)):
            s = FederationSettings(enabled=True, allow_localhost=True, require_approval=False, startup_wait_seconds=10,
                                   default_timeout_seconds=20, upstreams=[{'id': uid, 'url': url}])
            reg = Registry()
            managers[name] = FederationManager(reg, s, FederationStore(str(tmp_path / f'{name}.json')))
            managers[name].start()
        assert wait_for(lambda: 'pb__pong' in managers['a'].registry.tools and 'pa__ping' in managers['b'].registry.tools,
                        20)
        t0 = time.time()
        try:
            out = managers['a'].registry.tools['pb__pong'].execute({'q': 'x'})
        except Exception as e:
            out = str(e)
        text = json.dumps(out, default=str)
        assert 'tools.max_call_depth' in text and 'cycle' in text, text
        assert seen == [1, 2, 3, 4] and time.time() - t0 < 30
    finally:
        for m in managers.values():
            m.stop()
        for uv in (uv_a, uv_b):
            uv.should_exit = True


def test_the_mcp_handler_runs_a_call_with_the_carried_depth():
    from sajha.core import inner_calls
    from sajha.core.mcp_handler import MCPHandler
    got = []
    h = MCPHandler.__new__(MCPHandler)
    h._handle_request = lambda req, session: got.append(inner_calls.proxy_depth()) or {'jsonrpc': '2.0', 'id': 1,
                                                                                        'result': {}}
    h.handle_request({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                      'params': {'name': 'x', '_meta': {'io.sajha/chain': {'depth': 3}}}})
    h.handle_request({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'x'}})
    assert got == [3, 0] and inner_calls.proxy_depth() == 0
    with inner_calls.proxied_entered(inner_calls.max_depth()):
        with pytest.raises(inner_calls.CallTooDeep, match='max_call_depth'):
            inner_calls.proxy_outgoing('pb__pong')
        with pytest.raises(inner_calls.CallTooDeep):
            with inner_calls.entered('composite_x'):
                pass
