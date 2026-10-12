# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
Federation, complete (docs/architecture/Federation.md): what an upstream offers beyond tools,
prompts and resources is carried through SAJHA with the same namespacing and access rules.

* resource templates (resources/templates/list, reading an expanded URI);
* completions for a proxied prompt's and resource template's arguments;
* resources/subscribe and notifications/resources/updated (both upstream eras);
* upstream tasks (the tasks extension): followed to the end, cancelled upstream;
* MCP Apps views (ui://) of proxied tools, namespaced, with SAJHA's view rules;
* a 2025-11-25 upstream's requests to the client (sampling, elicitation, roots) relayed to a
  caller that can answer, refused with a clear error otherwise.

The upstream is an official MCP SDK v2 server (MCPServer) with the Apps extension and a small
tasks extension, served on a local port in a thread.
"""

import asyncio
import threading
import time
import uuid
from typing import Any

import pytest

pytest.importorskip('mcp.server.mcpserver')

from mcp.server.apps import Apps  # noqa: E402
from mcp.server.extension import Extension, MethodBinding  # noqa: E402
from mcp.server.mcpserver import Context, MCPServer  # noqa: E402
from mcp_types import (Completion, RequestParams, SamplingMessage, SubscribeRequestParams,  # noqa: E402
                       TextContent, UnsubscribeRequestParams)

from sajha.federation.config import FederationSettings  # noqa: E402
from sajha.federation.manager import FederationManager  # noqa: E402
from sajha.federation.store import FederationStore  # noqa: E402
from tests.test_federation import Registry, _free_port, wait_for  # noqa: E402

VIEW_HTML = '<!doctype html><html><body><p>chart</p></body></html>'
FACTORS = {'km': 0.621371, 'kg': 2.204623, 'kelvin': 1.0}


class TaskIdParams(RequestParams):
    task_id: str


class TasksExt(Extension):
    """The tasks extension (SEP-2663), just enough of it: long_job answers with a task."""
    identifier = 'io.modelcontextprotocol/tasks'

    def __init__(self):
        self.tasks = {}
        self.cancelled = []

    def methods(self):
        return [MethodBinding('tasks/get', TaskIdParams, self._get),
                MethodBinding('tasks/cancel', TaskIdParams, self._cancel)]

    async def intercept_tool_call(self, params, ctx, call_next):
        meta = (ctx.meta or {}) if hasattr(ctx, 'meta') else {}
        caps = meta.get('io.modelcontextprotocol/clientCapabilities') or {}
        declared = self.identifier in ((caps.get('extensions') if isinstance(caps, dict) else None) or {})
        if params.name != 'long_job' or not declared:
            return await call_next(ctx)
        seconds = float((params.arguments or {}).get('seconds', 0.2))
        tid = uuid.uuid4().hex
        now = '2026-10-11T00:00:00.000Z'
        self.tasks[tid] = {'taskId': tid, 'status': 'working', 'createdAt': now, 'lastUpdatedAt': now,
                           'ttlMs': 60000, 'pollIntervalMs': 50}

        async def run():
            await asyncio.sleep(seconds)
            if self.tasks[tid]['status'] == 'working':
                self.tasks[tid].update(status='completed', result={
                    'content': [{'type': 'text', 'text': f'job done in a task after {seconds}s'}],
                    'structuredContent': {'result': 'job done (task)'}})
        self.tasks[tid]['_runner'] = asyncio.get_running_loop().create_task(run())
        return {'resultType': 'task', **{k: v for k, v in self.tasks[tid].items() if not k.startswith('_')}}

    async def _get(self, ctx, params):
        t = self.tasks[params.task_id]
        return {'resultType': 'complete', **{k: v for k, v in t.items() if not k.startswith('_')}}

    async def _cancel(self, ctx, params):
        t = self.tasks[params.task_id]
        t['status'] = 'cancelled'
        t['_runner'].cancel()
        self.cancelled.append(params.task_id)
        return {'resultType': 'complete'}


class Upstream:
    def __init__(self):
        import uvicorn
        self.tasks = TasksExt()
        self.subscribed = []
        apps = Apps()

        @apps.tool(resource_uri='ui://units/chart.html', description='A chart with an MCP App view.')
        def chart() -> str:
            return 'chart data'
        apps.add_html_resource('ui://units/chart.html', VIEW_HTML, name='chart', prefers_border=False)

        async def task_support(ctx, call_next):
            # long_job declares task support (the 2026-07-28 core Tool has no execution field: on the wire)
            result = await call_next(ctx)
            for t in (result.get('tools') or []) if isinstance(result, dict) else []:
                if isinstance(t, dict) and t.get('name') == 'long_job':
                    t['execution'] = {'taskSupport': 'optional'}
            return result
        srv = MCPServer('complete-upstream', version='1.0.0', extensions=[apps, self.tasks],
                        middleware=[task_support])

        @srv.prompt(description='Explain one unit.')
        def explain_unit(unit: str) -> str:
            return f'Explain the unit {unit}.'

        @srv.resource('units://factor/{unit}', name='factor', description='The conversion factor of a unit.',
                      mime_type='text/plain')
        def factor(unit: str) -> str:
            return str(FACTORS.get(unit, 'unknown'))

        @srv.resource('units://counter', name='counter', description='A counter that changes.')
        def counter() -> str:
            return 'counter'

        @srv.completion()
        async def complete(ref, argument, context):
            if argument.name == 'unit':
                return Completion(values=[u for u in sorted(FACTORS) if u.startswith(argument.value)])
            return None

        @srv.tool(description='Says the counter changed.')
        async def bump(ctx: Context) -> str:
            if ctx.protocol_version and ctx.protocol_version >= '2026-07-28':
                await ctx.notify_resource_updated('units://counter')
            else:
                await ctx.session.send_resource_updated('units://counter')
            return 'bumped'

        @srv.tool(description='A long job (a task when the client supports tasks).')
        async def long_job(seconds: float = 0.2) -> str:
            await asyncio.sleep(seconds)
            return 'job done (sync)'

        @srv.tool(description='Asks the client model for a word.')
        async def ask_model(ctx: Context) -> str:
            r = await ctx.session.create_message(
                messages=[SamplingMessage(role='user', content=TextContent(type='text', text='a word?'))],
                max_tokens=10)
            return f'model said {r.content.text}'

        @srv.tool(description='Lists the client roots.')
        async def my_roots(ctx: Context) -> str:
            r = await ctx.session.list_roots()
            return ','.join(str(x.uri) for x in r.roots)

        @srv.tool(description='Asks the user to confirm.')
        async def confirm_it(ctx: Context) -> str:
            from pydantic import BaseModel

            class Ok(BaseModel):
                ok: bool
            r = await ctx.elicit('Go ahead?', Ok)
            return f'{r.action}:{bool(r.data and r.data.ok)}'

        async def on_subscribe(ctx, params):
            self.subscribed.append(params.uri)
            return {}

        async def on_unsubscribe(ctx, params):
            self.subscribed.append('-' + params.uri)
            return {}
        srv._lowlevel_server.add_request_handler('resources/subscribe', SubscribeRequestParams, on_subscribe)
        srv._lowlevel_server.add_request_handler('resources/unsubscribe', UnsubscribeRequestParams, on_unsubscribe)

        self.server = srv
        self.port = _free_port()
        self.url = f'http://127.0.0.1:{self.port}/mcp'
        self._uv = uvicorn.Server(uvicorn.Config(srv.streamable_http_app(), host='127.0.0.1', port=self.port,
                                                 log_level='warning',
                                                 timeout_graceful_shutdown=1))   # open streams: stop in 1 s, not 10
        self._thread = threading.Thread(target=self._uv.run, daemon=True)
        self._thread.start()
        deadline = time.time() + 10
        while not self._uv.started and time.time() < deadline:
            time.sleep(0.02)
        assert self._uv.started

    def stop(self):
        self._uv.should_exit = True
        self._thread.join(timeout=10)


@pytest.fixture(autouse=True)
def _no_policy_engine(monkeypatch):
    monkeypatch.setenv('SAJHA_POLICY_ENABLED', 'false')


@pytest.fixture(scope='module')
def upstream():
    u = Upstream()
    yield u
    u.stop()


@pytest.fixture
def make(tmp_path, monkeypatch):
    import sajha.federation.manager as fm
    made = []

    def _make(protocol='auto', **kw):
        settings = FederationSettings(enabled=True, allow_localhost=True, require_approval=False,
                                      startup_wait_seconds=10, default_timeout_seconds=10,
                                      upstreams=[{'id': 'units', 'url': kw.pop('url'), 'protocol': protocol,
                                                  'expose_prompts': True, 'expose_resources': True, **kw}])
        reg = Registry()
        m = FederationManager(reg, settings, FederationStore(str(tmp_path / f'fed{len(made)}.json')))
        m.start()
        made.append(m)
        monkeypatch.setattr(fm, '_manager', m)
        return m, reg
    yield _make
    for m in made:
        m.stop()


def handler(reg, auth=None):
    from sajha.core.mcp_handler import MCPHandler
    return MCPHandler(tools_registry=reg, auth_manager=auth)


ERAS = [('auto', '2026-07-28'), ('legacy', '2025-11-25')]


# ── 1. resource templates ───────────────────────────────────────────

@pytest.mark.parametrize('protocol,version', ERAS)
def test_resource_templates_are_listed_and_read(upstream, make, protocol, version):
    m, reg = make(protocol, url=upstream.url)
    assert m.status('units')['protocol_version'] == version
    h = handler(reg)
    templates = [t for t in h._handle_resources_templates_list({})['resourceTemplates']
                 if t['uriTemplate'].startswith('sajha-federation://')]
    assert templates == [{'uriTemplate': 'sajha-federation://units/units%3A%2F%2Ffactor%2F{unit}',
                          'name': 'units__factor', 'description': 'The conversion factor of a unit.',
                          'mimeType': 'text/plain'}]
    # a client expands the template as usual; SAJHA routes the expansion to the upstream's own URI
    uri = templates[0]['uriTemplate'].replace('{unit}', 'km')
    body = h._handle_resources_read({'uri': uri})
    assert body['contents'][0]['text'] == '0.621371' and body['contents'][0]['uri'] == uri
    # not an expansion of an approved template: not found
    from sajha.core.mcp_2025_11_25 import MCPError
    with pytest.raises(MCPError):
        h._handle_resources_read({'uri': 'sajha-federation://units/units%3A%2F%2Fsecret'})


def test_templates_need_approval_and_follow_the_resource_rule(upstream, make):
    from sajha.auth.access import SessionToolAccess
    from sajha.core.mcp_2025_11_25 import MCPError
    m, reg = make(url=upstream.url)
    m.set_item_status('units', 'template', 'units://factor/{unit}', 'reject')
    h = handler(reg)
    assert not [t for t in h._handle_resources_templates_list({})['resourceTemplates']
                if t['uriTemplate'].startswith('sajha-federation://')]
    with pytest.raises(MCPError):
        h._handle_resources_read({'uri': 'sajha-federation://units/units%3A%2F%2Ffactor%2Fkm'})
    m.set_item_status('units', 'template', 'units://factor/{unit}', 'approve')
    # a signed-in caller without a resource rule for it sees no template and reads nothing
    h = handler(reg, SessionToolAccess())
    who = {'user_id': 'u', 'authenticated': True, 'resource_rules': [[]]}
    assert not [t for t in h._handle_resources_templates_list({}, who)['resourceTemplates']
                if t['uriTemplate'].startswith('sajha-federation://')]
    with pytest.raises(MCPError):
        h._handle_resources_read({'uri': 'sajha-federation://units/units%3A%2F%2Ffactor%2Fkm'}, who)


# ── 2. completions ──────────────────────────────────────────────────

@pytest.mark.parametrize('protocol,version', ERAS)
def test_completions_for_prompts_and_templates(upstream, make, protocol, version):
    m, reg = make(protocol, url=upstream.url)
    h = handler(reg)
    got = h._handle_completion_complete({'ref': {'type': 'ref/prompt', 'name': 'units__explain_unit'},
                                         'argument': {'name': 'unit', 'value': 'k'}})
    assert got['completion']['values'] == ['kelvin', 'kg', 'km']
    tmpl = 'sajha-federation://units/units%3A%2F%2Ffactor%2F{unit}'
    got = h._handle_completion_complete({'ref': {'type': 'ref/resource', 'uri': tmpl},
                                         'argument': {'name': 'unit', 'value': 'kg'}})
    assert got['completion']['values'] == ['kg']
    # hidden from the caller: no values
    from sajha.auth.access import SessionToolAccess
    hidden = handler(reg, SessionToolAccess())
    who = {'user_id': 'u', 'authenticated': True, 'prompt_rules': [[]], 'resource_rules': [[]]}
    got = hidden._handle_completion_complete({'ref': {'type': 'ref/prompt', 'name': 'units__explain_unit'},
                                              'argument': {'name': 'unit', 'value': 'k'}}, who)
    assert got['completion']['values'] == []


# ── 3. resources/subscribe ──────────────────────────────────────────

@pytest.mark.parametrize('protocol,version', ERAS)
def test_subscriptions_reach_the_upstream_and_updates_come_back(upstream, make, protocol, version):
    from sajha.core.change_bus import RESOURCE_UPDATED, get_change_bus
    m, reg = make(protocol, url=upstream.url)
    uri = 'sajha-federation://units/units%3A%2F%2Fcounter'
    assert m.subscribe_problem(uri) is None
    seen = []

    def on_change(event):
        if event.kind == RESOURCE_UPDATED:
            seen.append(event.uri)
    bus = get_change_bus()
    bus.add_listener(on_change)
    try:
        before = len(upstream.subscribed)
        m.watch('test-holder', uri)
        if version == '2025-11-25':
            assert wait_for(lambda: 'units://counter' in upstream.subscribed[before:], 5)
        else:
            assert wait_for(lambda: m._upstreams['units'].conn.listening, 5)
            time.sleep(0.3)                     # the listen stream reopened with the subscription
        reg.tools['units__bump'].execute({})
        assert wait_for(lambda: uri in seen, 5), seen
        m.release('test-holder')
        if version == '2025-11-25':
            assert wait_for(lambda: '-units://counter' in upstream.subscribed[before:], 5)
    finally:
        bus.remove_listener(on_change)


def test_subscribe_through_a_session(upstream, make):
    """resources/subscribe on a 2025-11-25 session records the URI and holds the upstream subscription
    until the session unsubscribes."""
    from sajha.core.mcp_sessions import get_session_store
    from sajha.core.mcp_2025_11_25 import MCPError
    m, reg = make('legacy', url=upstream.url)
    s = get_session_store().create(protocol_version='2025-11-25', client_info={}, client_capabilities={})
    h = handler(reg)
    uri = 'sajha-federation://units/units%3A%2F%2Fcounter'
    who = {'mcp_session_id': s.session_id}
    assert h._handle_resources_subscribe({'uri': uri}, who) == {}
    assert uri in s.subscriptions and m.watched_uris() == [uri]
    with pytest.raises(MCPError):
        h._handle_resources_subscribe({'uri': 'sajha-federation://units/units%3A%2F%2Fnope'}, who)
    h._handle_resources_unsubscribe({'uri': uri}, who)
    assert uri not in s.subscriptions and m.watched_uris() == []
    get_session_store().delete(s.session_id)


def test_modern_listen_honors_federated_subscriptions(upstream, make):
    from sajha.core.mcp_modern import ModernMCPServer
    m, reg = make(url=upstream.url)
    srv = ModernMCPServer(handler(reg))
    keep, federated = srv._federated_subscriptions(
        ['sajha-federation://units/units%3A%2F%2Fcounter', 'sajha-federation://units/units%3A%2F%2Fnope',
         'sajha://tools/catalog'], None)
    assert keep == ['sajha-federation://units/units%3A%2F%2Fcounter', 'sajha://tools/catalog']
    assert federated == ['sajha-federation://units/units%3A%2F%2Fcounter']


# ── 4. upstream tasks ───────────────────────────────────────────────

def test_upstream_task_is_followed_and_offered_as_a_task(upstream, make):
    m, reg = make(url=upstream.url)
    tool = reg.tools['units__long_job']
    assert tool.config['execution'] == {'taskSupport': 'optional'}     # SAJHA offers it as a task too
    h = handler(reg)
    assert h.tool_task_support('units__long_job') == 'optional'
    out = tool.execute({'seconds': 0.2})
    assert out['structuredContent'] == {'result': 'job done (task)'}
    assert upstream.tasks.tasks                                        # it ran as an upstream task


def test_cancelling_reaches_the_upstream_task(upstream, make):
    from sajha.core.mcp_tool_context import ModernToolContext
    m, reg = make(url=upstream.url)
    ctx = ModernToolContext()
    threading.Timer(0.5, ctx.cancel).start()
    token = ctx.activate()
    t0 = time.time()
    try:
        with pytest.raises(RuntimeError, match='cancelled'):
            reg.tools['units__long_job'].execute({'seconds': 10})
    finally:
        ctx.deactivate(token)
    assert time.time() - t0 < 4
    assert wait_for(lambda: upstream.tasks.cancelled, 5)


def test_legacy_upstream_runs_the_tool_without_a_task(upstream, make):
    m, reg = make('legacy', url=upstream.url)
    assert reg.tools['units__long_job'].execute({'seconds': 0.05})['structuredContent'] == {
        'result': 'job done (sync)'}


# ── 5. MCP Apps views ───────────────────────────────────────────────

def test_views_are_namespaced_listed_and_read(upstream, make):
    from sajha.core import mcp_apps
    from sajha.core.mcp_2025_11_25 import MCPError
    m, reg = make(url=upstream.url)
    tool = reg.tools['units__chart']
    view = 'ui://sajha-federation/units/ui%3A%2F%2Funits%2Fchart.html'
    assert tool.config['_meta']['ui']['resourceUri'] == view
    assert mcp_apps.tool_ui_meta(tool.config, tool.name)['resourceUri'] == view
    h = handler(reg)
    listed = h._handle_tools_list({}, None, 'modern')['tools']
    assert next(t for t in listed if t['name'] == 'units__chart')['_meta']['ui']['resourceUri'] == view
    legacy = h._handle_tools_list({}, None)['tools']
    assert 'ui' not in next(t for t in legacy if t['name'] == 'units__chart').get('_meta', {})
    assert [v['uri'] for v in h.federated_views(None)] == [view]
    body = h._handle_resources_read({'uri': view})
    c = body['contents'][0]
    assert c['text'] == VIEW_HTML and c['mimeType'] == mcp_apps.APP_MIME_TYPE and c['uri'] == view
    assert c['_meta'] == {'ui': {'prefersBorder': False}}     # no CSP domains, no permissions
    # a caller who may not see the tool cannot see or read its view
    from sajha.auth.access import SessionToolAccess, apikey_policy
    hidden = handler(reg, SessionToolAccess())
    who = {'user_id': 'k', 'authenticated': True, **apikey_policy('allowlist', ['units__bump']).to_session()}
    assert hidden.federated_views(who) == []
    with pytest.raises(MCPError):
        hidden._handle_resources_read({'uri': view}, who)


# ── 6. requests from a 2025-11-25 upstream to the client ────────────

class FakeCallCtx:
    """What a 2025-11-25 transport gives the relay: a request to the client, answered."""

    def __init__(self, answers):
        self.answers = answers
        self.asked = []

    async def request(self, method, params, timeout=120.0):
        self.asked.append((method, params))
        return self.answers[method]


@pytest.fixture
def loop_thread():
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=5)


def test_requests_to_the_client_are_relayed(upstream, make, loop_thread):
    from sajha.federation import relay
    m, reg = make('legacy', url=upstream.url)
    call = FakeCallCtx({
        'sampling/createMessage': {'role': 'assistant', 'content': {'type': 'text', 'text': 'banana'},
                                   'model': 'client-model'},
        'roots/list': {'roots': [{'uri': 'file:///work', 'name': 'work'}]},
        'elicitation/create': {'action': 'accept', 'content': {'ok': True}}})
    r = relay.ClientRelay(call, loop_thread, {'sampling': {}, 'roots': {}, 'elicitation': {'form': {}}})
    for name, want in (('units__ask_model', 'model said banana'), ('units__my_roots', 'file:///work'),
                       ('units__confirm_it', 'accept:True')):
        with relay.bound(r, name):
            out = reg.tools[name].execute({})
        assert out['structuredContent'] == {'result': want}, (name, out)
    assert [a[0] for a in call.asked] == ['sampling/createMessage', 'roots/list', 'elicitation/create']


def test_requests_to_the_client_are_refused_clearly(upstream, make, loop_thread):
    from sajha.federation import relay
    m, reg = make('legacy', url=upstream.url)
    # no relay (a 2026-07-28 caller, REST, A2A, Ask SAJHA, or a client that took no stream)
    with pytest.raises(Exception, match='cannot pass elicitation/create to its caller'):
        reg.tools['units__confirm_it'].execute({})
    # a relay, but the caller did not declare sampling
    r = relay.ClientRelay(FakeCallCtx({}), loop_thread, {'elicitation': {}})
    with relay.bound(r, 'units__ask_model'):
        with pytest.raises(Exception, match='[Ss]ampling'):
            reg.tools['units__ask_model'].execute({})


def test_relay_capability_rules():
    from sajha.federation.relay import caller_supports, wanted
    assert caller_supports({'elicitation': {}}, 'elicitation/create', {'mode': 'form'})
    assert not caller_supports({'elicitation': {}}, 'elicitation/create', {'mode': 'url'})
    assert caller_supports({'elicitation': {'url': {}}}, 'elicitation/create', {'mode': 'url'})
    assert not caller_supports({}, 'sampling/createMessage')
    assert wanted({'sampling': {}}) and not wanted({'roots': {}})


def test_session_relay_end_to_end(upstream, tmp_path_factory):
    """Over the app: a 2025-11-25 session that declares sampling calls a proxied tool with an SSE
    response; the upstream's sampling/createMessage arrives on that stream and the client's answer,
    POSTed back, reaches the upstream."""
    import json
    import os
    from fastapi.testclient import TestClient
    state = tmp_path_factory.mktemp('fedc') / 'federation.json'
    env = {'SAJHA_FEDERATION_ENABLED': 'true', 'SAJHA_FEDERATION_ALLOW_LOCALHOST': 'true',
           'SAJHA_FEDERATION_REQUIRE_APPROVAL': 'false', 'SAJHA_FEDERATION_STATE_PATH': str(state),
           'SAJHA_FEDERATION_UPSTREAMS': f'[{{"id": "units", "url": "{upstream.url}", "protocol": "legacy", "expose_resources": true}}]',
           'SAJHA_MCP_ANONYMOUS_TOOLS': 'units__*', 'SAJHA_MCP_ANONYMOUS_RESOURCES': 'sajha-federation://*'}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        from sajha.app import create_app
        with TestClient(create_app()) as c:      # the TestClient buffers a streamed response: a real socket
            import httpx
            import uvicorn
            port = _free_port()
            server = uvicorn.Server(uvicorn.Config(c.app, host='127.0.0.1', port=port, lifespan='off',
                                                   log_level='error'))
            th = threading.Thread(target=server.run, daemon=True)
            th.start()
            try:
                assert wait_for(lambda: server.started, 10)
                base = f'http://127.0.0.1:{port}/mcp'
                with httpx.Client(timeout=30) as hc, httpx.Client(timeout=30) as other:
                    init = hc.post(base, json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                        'protocolVersion': '2025-11-25', 'capabilities': {'sampling': {}},
                        'clientInfo': {'name': 't', 'version': '1'}}})
                    assert init.json()['result']['capabilities']['resources']['subscribe'] is True
                    hdr = {'MCP-Protocol-Version': '2025-11-25', 'Mcp-Session-Id': init.headers['mcp-session-id']}
                    hc.post(base, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'}, headers=hdr)
                    asked, final = [], None
                    with hc.stream('POST', base, headers={**hdr, 'Accept': 'application/json, text/event-stream'},
                                   json={'jsonrpc': '2.0', 'id': 9, 'method': 'tools/call',
                                         'params': {'name': 'units__ask_model', 'arguments': {}}}) as r:
                        for line in r.iter_lines():
                            if not line.startswith('data:') or not line[5:].strip():
                                continue
                            msg = json.loads(line[5:])
                            if msg.get('method') == 'sampling/createMessage':
                                asked.append(msg)
                                ack = other.post(base, headers=hdr, json={'jsonrpc': '2.0', 'id': msg['id'], 'result': {
                                    'role': 'assistant', 'content': {'type': 'text', 'text': 'kiwi'}, 'model': 'm'}})
                                assert ack.status_code == 202
                            elif msg.get('id') == 9:
                                final = msg
                                break
                    # resources/subscribe on the session: the update arrives on its GET /mcp stream
                    uri = 'sajha-federation://units/units%3A%2F%2Fcounter'
                    updates = []

                    def listen():
                        with httpx.Client(timeout=30) as gc, gc.stream(
                                'GET', base, headers={**hdr, 'Accept': 'text/event-stream'}) as g:
                            for line in g.iter_lines():
                                if line.startswith('data:') and line[5:].strip():
                                    msg = json.loads(line[5:])
                                    if msg.get('method') == 'notifications/resources/updated':
                                        updates.append(msg['params']['uri'])
                                        return
                    lt = threading.Thread(target=listen, daemon=True)
                    lt.start()
                    time.sleep(0.5)
                    before = len(upstream.subscribed)
                    r = hc.post(base, headers=hdr, json={'jsonrpc': '2.0', 'id': 10, 'method': 'resources/subscribe',
                                                         'params': {'uri': uri}})
                    assert r.json().get('result') == {}, r.text
                    assert wait_for(lambda: 'units://counter' in upstream.subscribed[before:], 5)
                    hc.post(base, headers=hdr, json={'jsonrpc': '2.0', 'id': 11, 'method': 'tools/call',
                                                     'params': {'name': 'units__bump', 'arguments': {}}})
                    lt.join(10)
                    assert updates == [uri]
                    hc.delete(base, headers=hdr)
                    assert wait_for(lambda: '-units://counter' in upstream.subscribed[before:], 5)
                assert asked and asked[0]['params']['messages'][0]['content']['text'] == 'a word?'
                assert final['result']['structuredContent'] == {'result': 'model said kiwi'}, final
            finally:
                server.should_exit = True
                th.join(5)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
