"""
SAJHA MCP Server v3 — MCP Protocol Routes (SSE + Extended Methods)
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Implements the Streamable HTTP transport (SSE) per MCP spec,
plus resources, completion, and logging endpoints.
"""

import json
import uuid
import asyncio
import logging
from datetime import datetime

from starlette.concurrency import run_in_threadpool
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse, Response
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from sajha.db.engine import get_db, release_session
from sajha.auth import AuthManager, AuthContext, require_admin, require_auth
from sajha.auth.oauth.resource_server import authorize_mcp

logger = logging.getLogger(__name__)
router = APIRouter(tags=['mcp'])

# ── Legacy (2024-11-05) SSE sessions ─────────────────────────────
# Queues live in sajha.core.mcp_sse_relay, which relays responses between workers
# when a shared state store is configured (docs/architecture/Scaling and State.md).
from sajha.core import mcp_sse_relay as _sse_relay

_SESSION_HEADER = 'mcp-session-id'
_VERSION_HEADER = 'mcp-protocol-version'


def _rpc_error(code: int, message: str, status: int, rid=None, headers=None) -> JSONResponse:
    return JSONResponse({'jsonrpc': '2.0', 'id': rid, 'error': {'code': code, 'message': message}},
                        status_code=status, headers=headers)


def _check_origin(request: Request):
    """403 for a disallowed Origin (DNS-rebinding protection), else None."""
    from sajha.core.mcp_2025_11_25 import validate_origin
    origin = request.headers.get('origin')
    if not validate_origin(origin):
        logger.warning(f"Rejected MCP request from disallowed Origin: {origin}")
        return _rpc_error(-32000, 'Forbidden: Origin not allowed', 403)
    return None


def _check_protocol_header(request: Request):
    """400 when MCP-Protocol-Version names a version this server does not support."""
    from sajha.core.mcp_2025_11_25 import SUPPORTED_PROTOCOL_VERSIONS
    version = request.headers.get(_VERSION_HEADER)
    if version and version not in SUPPORTED_PROTOCOL_VERSIONS:
        return _rpc_error(-32000, f'Unsupported MCP-Protocol-Version: {version}. '
                                  f'Supported: {", ".join(SUPPORTED_PROTOCOL_VERSIONS)}', 400)
    return None


def _lookup_session(request: Request):
    """Return (session, error_response). Unknown session id -> 404."""
    from sajha.core.mcp_sessions import get_session_store
    sid = request.headers.get(_SESSION_HEADER)
    if not sid:
        return None, None
    session = get_session_store().get(sid)
    if session is None:
        return None, _rpc_error(-32001, 'Session not found', 404)
    return session, None


def with_push_capabilities(response):
    """
    An initialize response for a transport with a server -> client push
    channel (streamable-HTTP sessions, whose GET /mcp stream carries them;
    2024-11-05 HTTP+SSE stream; WebSocket): those receive list_changed
    notifications from the change bus, so they advertise listChanged.  The
    shared handler capabilities keep it false.
    """
    import copy
    if not isinstance(response, dict) or not isinstance(response.get('result'), dict):
        return response
    response = copy.deepcopy(response)
    caps = response['result'].setdefault('capabilities', {})
    for key in ('tools', 'prompts', 'resources'):
        if isinstance(caps.get(key), dict):
            caps[key]['listChanged'] = True
    return response


async def forward_changes(queue: asyncio.Queue):
    """Copy change-bus list_changed events into a legacy push queue until cancelled."""
    from sajha.core.change_bus import get_change_bus, TOOLS, PROMPTS, RESOURCES
    sub = get_change_bus().subscribe({TOOLS, PROMPTS, RESOURCES})
    try:
        while True:
            event = await sub.get()
            if event is None:
                return
            await queue.put(event.notification())
    finally:
        sub.close()


# ── Streamable HTTP: POST /mcp ───────────────────────────────────

@router.post('/mcp')
@router.post('/api/mcp')
async def mcp_post(request: Request, db: Session = Depends(get_db)):
    """
    MCP Streamable HTTP transport — client -> server messages.  Dual-era:

    * 2026-07-28 (modern): a body whose params._meta carries
      io.modelcontextprotocol/protocolVersion (or an MCP-Protocol-Version
      header naming a non-handshake version) is served statelessly by
      sajha.core.mcp_modern — no sessions, header/body validation,
      server/discover, resultType + caching hints on results.
    * 2025-11-25 and earlier (legacy), everything else:

    - request      -> JSON-RPC response (application/json), or an SSE stream
                      for tools that talk to the client while running
    - notification -> 202 Accepted, empty body
    - response     -> 202 Accepted (answer to a server -> client request)
    - JSON array   -> 400 / -32600 (batching was removed in 2025-06-18;
                      the WebSocket transport still accepts batches)
    """
    from sajha.app import mcp_handler
    from sajha.core.mcp_sessions import get_session_store
    from sajha.core import mcp_modern

    err = _check_origin(request)
    if err is not None:
        return err

    raw = await request.body()

    # SAJHA Net (docs/protocol/SAJHA Net Protocol.md §15): a request carrying Sajha-Net-* headers is a
    # signed request from a participant; it is verified and served by the net, or refused, never
    # served as an anonymous or ordinarily authenticated request
    if any(k.lower().startswith('sajha-net-') for k in request.headers.keys()):
        return await _serve_net(request, raw)

    try:
        body = json.loads(raw)
        parsed = True
    except (ValueError, RecursionError):
        body, parsed = None, False

    # Authorization (mcp.auth.mode): API keys / SAJHA JWTs / OAuth bearer tokens;
    # 401/403 with a WWW-Authenticate challenge when OAuth is enforced.
    method = body.get('method') if isinstance(body, dict) and isinstance(body.get('method'), str) else None
    auth, err = await authorize_mcp(request, db, method)
    if err is not None:
        return err

    # ── MCP 2026-07-28: stateless, per-request _meta envelope ──
    # Mcp-Session-Id / Last-Event-ID are ignored on this path and no session is minted.
    if mcp_modern.is_modern_request(body, request.headers):
        if not parsed:
            status, payload = mcp_modern.parse_error_response()
        else:
            session_data = auth.to_legacy_session()  # identity + tool policy (anonymous too)
            outcome = await _modern_server(mcp_handler).handle(
                body, request.headers, list(request.headers.items()), session_data,
                receive=request.receive)
            if isinstance(outcome, mcp_modern.ModernStream):
                # 2026-07-28 streams carry no event ids: there is no resumability
                return EventSourceResponse(outcome.events(), ping=15)
            status, payload = outcome
        if payload is None:
            return Response(status_code=status)
        return JSONResponse(payload, status_code=status)

    # ── Legacy (initialize handshake) path: 2025-11-25 and earlier ──
    err = _check_protocol_header(request)
    if err is not None:
        return err
    mcp_session, err = _lookup_session(request)
    if err is not None:
        return err

    if not parsed:
        return _rpc_error(-32700, 'Parse error', 400)

    if isinstance(body, list):
        return _rpc_error(-32600, 'Invalid Request: JSON-RPC batches are not supported '
                                  'on this transport (removed in MCP 2025-06-18)', 400)
    if not isinstance(body, dict):
        return _rpc_error(-32600, 'Invalid Request', 400)

    store = get_session_store()

    # A JSON-RPC response from the client (to sampling/elicitation etc.)
    if 'method' not in body and 'id' in body and ('result' in body or 'error' in body):
        if not store.resolve_response(mcp_session, body):
            logger.debug(f"Unmatched client response id={body.get('id')!r}")
        return Response(status_code=202)

    session_data = auth.to_legacy_session()  # identity + tool policy (anonymous too)
    if mcp_session is not None:     # what the client can do (URL elicitation: sajha/accounts/respond.py)
        session_data['client_capabilities'] = dict(mcp_session.client_capabilities or {})
        session_data['mcp_session_id'] = mcp_session.session_id     # resources/subscribe (mcp_handler)

    # Notification: no id -> 202, no body
    if body.get('jsonrpc') == '2.0' and isinstance(body.get('method'), str) and 'id' not in body:
        scope = _cancel_scope(request, mcp_session)
        if body['method'] == 'notifications/cancelled' and scope is not None:
            # stop the named in-flight call (federation passes it on upstream): mcp_cancellation
            from sajha.core import mcp_cancellation
            cp = body.get('params') if isinstance(body.get('params'), dict) else {}
            mcp_cancellation.cancel(scope, cp.get('requestId'), cp.get('reason'))
        await run_in_threadpool(mcp_handler.handle_request, body, session_data)
        if mcp_session and body['method'] in ('notifications/initialized', 'initialized'):
            mcp_session.initialized = True
        return Response(status_code=202)

    method = body.get('method')
    params = body.get('params') if isinstance(body.get('params'), dict) else {}
    legacy_sid = request.query_params.get('session')
    legacy_sid = legacy_sid if legacy_sid and _sse_relay.exists(legacy_sid) else None

    # Tools that interact with the client while running (conformance fixtures)
    if method == 'tools/call':
        from sajha.core.mcp_conformance_fixtures import get_conformance_fixtures
        fixtures = get_conformance_fixtures()
        if fixtures and fixtures.is_async_tool(params.get('name', '')):
            return await _stream_tool_call(request, body, params, fixtures, mcp_session)
        # An LLM tool with llm.sampling prefer|require: its model call goes to the client as a
        # sampling/createMessage request on this call's SSE stream (docs/architecture/LLM Tools.md §12)
        wants_sse = 'text/event-stream' in request.headers.get('accept', '')
        sampled = (mcp_session is not None and mcp_session.supports('sampling') and wants_sse
                   and _samples(mcp_handler, params.get('name')))
        # An answer-mode LLM tool (sajha_ask): a destructive call it wants to make is confirmed by the
        # user through an elicitation/create request on this call's SSE stream (Intelligence Layer §6)
        confirms = (mcp_session is not None and wants_sse and _elicits_form(mcp_session)
                    and _confirms(mcp_handler, params.get('name')))
        # A call with _meta.progressToken from a client that takes SSE: the tool's progress (a remote
        # SAJHA Net tool's too) streams before the result; without either, JSON as before
        # A proxied MCP server's tool: its upstream's requests to the client (sampling, elicitation, roots)
        # go to this client on this call's SSE stream (sajha/federation/relay.py, Federation.md section 7)
        relayed = (mcp_session is not None and wants_sse and not sampled and not confirms
                   and _relays(mcp_handler, params.get('name'), mcp_session))
        if sampled or confirms or relayed or (wants_sse and _progress_token(params) is not None and not legacy_sid):
            return await _stream_registry_call(body, params, session_data, mcp_session, mcp_handler, sampled,
                                               confirms, relayed)

    if method == 'tools/call' and legacy_sid:
        # 2024-11-05 HTTP+SSE: progress goes over the client's SSE stream, ahead of the response
        from sajha.core.mcp_tool_context import call_with_events
        response = await call_with_events(lambda: mcp_handler.handle_request(body, session_data), params,
                                          lambda m: _sse_relay.deliver(legacy_sid, m), legacy_sid, body.get('id'))
    elif method == 'tools/call':
        from sajha.core import mcp_cancellation
        with mcp_cancellation.track(getattr(mcp_session, 'session_id', None), body.get('id')):
            response = await run_in_threadpool(mcp_handler.handle_request, body, session_data)
    else:
        response = await run_in_threadpool(mcp_handler.handle_request, body, session_data)

    # Legacy 2024-11-05 HTTP+SSE client: the response travels over its SSE stream
    if legacy_sid:
        if method == 'initialize':
            response = with_push_capabilities(response)
        await _sse_relay.deliver(legacy_sid, response)
        return Response(status_code=202)

    headers = {}
    if method == 'initialize' and isinstance(response, dict) and 'result' in response:
        response = with_push_capabilities(response)     # the session's GET /mcp stream carries list_changed
        response = _with_subscribe(response)             # ... and notifications/resources/updated
        new_session = store.create(
            protocol_version=response['result'].get('protocolVersion'),
            client_info=params.get('clientInfo') or {},
            client_capabilities=params.get('capabilities') or {},
            user_id=(session_data or {}).get('user_id'),
        )
        headers['Mcp-Session-Id'] = new_session.session_id

    status = 400 if 'error' in response and response['error'].get('code') in (-32700, -32600) else 200
    return JSONResponse(response, status_code=status, headers=headers)


_modern_servers: dict = {}


async def _serve_net(request: Request, raw: bytes, svc=None) -> Response:
    """A signed participant request to the MCP endpoint (SAJHA Net §15.4); an unsigned 404 when SAJHA Net
    is off or the net is not one of this server's (§7.7). A streamed answer (§15.10) is sent as it is
    produced. ``svc``: the SAJHA Net service (default: this process's)."""
    from sajha.net.integration import get_service
    svc = svc if svc is not None else get_service()
    if svc is None or not svc.participant.enabled:
        return Response(status_code=404)
    proto = request.headers.get('x-forwarded-proto', '').split(',')[0].strip().lower()
    secure = request.url.scheme == 'https' or proto == 'https'
    source = request.client.host if request.client else ''
    r = await run_in_threadpool(svc.participant.handle_mcp, request.method, request.url.path, request.url.query,
                                dict(request.headers), raw, secure, source)
    if r is None:
        return Response(status_code=404)
    headers = {k: v for k, v in r.headers.items() if k.lower() != 'content-length'}
    if r.stream is not None:
        # a signed event stream (§15.10): chunks pulled off the event loop; a dropped home ends the
        # iteration and closes the stream, which cancels the call at this host
        from starlette.responses import StreamingResponse
        stream, close = r.stream, r.close

        async def body():
            try:
                while True:
                    chunk = await run_in_threadpool(next, stream, None)
                    if chunk is None:
                        break
                    yield chunk
            finally:
                if close is not None:
                    close()

        class _NetStream(StreamingResponse):
            # On ASGI 2.4 servers a dropped home surfaces as an error from send(), which leaves body()
            # suspended until garbage collection: close the stream as soon as the response ends, however
            # it ends (close is idempotent), so the host's tool sees the cancellation at once.
            async def __call__(self, scope, receive, send):
                try:
                    await super().__call__(scope, receive, send)
                finally:
                    if close is not None:
                        close()
        return _NetStream(body(), status_code=r.status, headers=headers)
    return Response(content=r.body, status_code=r.status, headers=headers)


def _modern_server(handler):
    """One ModernMCPServer per MCPHandler instance (the handler is rebuilt by create_app)."""
    from sajha.core.mcp_modern import ModernMCPServer
    server = _modern_servers.get(id(handler))
    if server is None or server.handler is not handler:
        _modern_servers.clear()
        server = _modern_servers[id(handler)] = ModernMCPServer(handler)
    return server


def _modern_405():
    """2026-07-28 has no GET stream and no sessions: GET/DELETE -> 405 (streamable-http, Backward Compatibility)."""
    return Response(status_code=405, headers={'Allow': 'POST'})


async def _stream_tool_call(request: Request, body: dict, params: dict, fixtures, mcp_session):
    """Run an async tool, streaming its notifications/requests and final result over SSE."""
    from sajha.core.mcp_sessions import ToolCallContext

    rid = body.get('id')
    name = params.get('name', '')
    args = params.get('arguments') or {}
    meta = params.get('_meta') or {}
    wants_sse = 'text/event-stream' in request.headers.get('accept', '')

    if not wants_sse:
        ctx = ToolCallContext(mcp_session, None, meta.get('progressToken'))
        result = await fixtures.call_tool_async(name, args, ctx)
        return JSONResponse({'jsonrpc': '2.0', 'id': rid, 'result': result})

    queue: asyncio.Queue = asyncio.Queue()
    ctx = ToolCallContext(mcp_session, queue, meta.get('progressToken'))
    stream_id = uuid.uuid4().hex[:12]

    async def events():
        counter = 0

        def next_id():
            nonlocal counter
            counter += 1
            return f"{stream_id}:{counter}"

        # Priming event (id + empty data) so the client can resume (SEP-1699)
        yield {'id': next_id(), 'data': ''}
        task = asyncio.create_task(fixtures.call_tool_async(name, args, ctx))
        try:
            while True:
                getter = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    yield {'id': next_id(), 'event': 'message', 'data': json.dumps(getter.result())}
                    continue
                getter.cancel()
                while not queue.empty():
                    yield {'id': next_id(), 'event': 'message', 'data': json.dumps(queue.get_nowait())}
                result = task.result()
                yield {'id': next_id(), 'event': 'message',
                       'data': json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': result})}
                return
        finally:
            if not task.done():
                task.cancel()

    return EventSourceResponse(events())


def _samples(handler, name) -> bool:
    """Is ``name`` an LLM tool that sends its model call to a client that can sample?"""
    registry = getattr(handler, 'tools_registry', None)
    tool = registry.get_tool(name) if registry is not None and isinstance(name, str) else None
    if tool is None:
        return False
    from sajha.ai.llm_tools.sampling import wants_sampling
    return wants_sampling(tool)


def _elicits_form(mcp_session) -> bool:
    from sajha.core.mcp_mrtr import elicitation_form_supported
    return elicitation_form_supported(getattr(mcp_session, 'client_capabilities', None) or {})


def _confirms(handler, name) -> bool:
    """Is ``name`` an answer-mode LLM tool, whose destructive inner calls the client's user may confirm?"""
    registry = getattr(handler, 'tools_registry', None)
    tool = registry.get_tool(name) if registry is not None and isinstance(name, str) else None
    if tool is None:
        return False
    from sajha.ai.llm_tools.confirmation import wants_confirmation
    return wants_confirmation(tool)


def _progress_token(params: dict):
    meta = params.get('_meta') if isinstance(params.get('_meta'), dict) else {}
    token = meta.get('progressToken')
    return token if isinstance(token, (str, int)) and not isinstance(token, bool) else None


def _cancel_scope(request: Request, mcp_session):
    """The mcp_cancellation scope of a 2025-11-25 request: its MCP session, or its 2024-11-05 SSE session."""
    if mcp_session is not None:
        return mcp_session.session_id
    sid = request.query_params.get('session')
    return sid if sid and _sse_relay.exists(sid) else None


def _relays(handler, name, mcp_session) -> bool:
    """Is ``name`` a proxied server's tool, called by a client that can answer its upstream's requests?"""
    registry = getattr(handler, 'tools_registry', None)
    tool = registry.get_tool(name) if registry is not None and isinstance(name, str) else None
    if tool is None or not hasattr(tool, 'upstream_id'):
        return False
    from sajha.federation.relay import wanted
    if not wanted(getattr(mcp_session, 'client_capabilities', None)):
        return False
    manager = getattr(tool, 'manager', None)
    return bool(manager is not None and manager.relays_for(tool))


def _with_subscribe(response):
    """A streamable-HTTP session's initialize result: resources.subscribe is true, because its GET /mcp
    stream carries notifications/resources/updated for the URIs it subscribed to."""
    result = response.get('result') if isinstance(response, dict) else None
    caps = result.get('capabilities') if isinstance(result, dict) else None
    if isinstance(caps, dict) and isinstance(caps.get('resources'), dict):
        caps['resources']['subscribe'] = True
    return response


async def _stream_registry_call(body: dict, params: dict, session_data: dict, mcp_session, handler,
                                sampled: bool = False, confirms: bool = False, relayed: bool = False):
    """tools/call of a registry tool over SSE (2025-11-25): the tool runs in a worker thread under a
    TransportToolContext, so its progress (and log, when the request set a logLevel) travels on this
    stream before the response; with ``sampled``, the 2025-11-25 sampling channel is bound too: the
    tool's sampling/createMessage requests travel here and the client's answers arrive as JSON-RPC
    responses on POST /mcp. With ``confirms``, an answer-mode LLM tool's destructive-call confirmations
    travel here the same way, as elicitation/create requests. A client notifications/cancelled reaches the
    tool (is_cancelled())."""
    from sajha.core.mcp_sessions import ToolCallContext
    from sajha.core.mcp_tool_context import ModernToolContext, TransportToolContext
    import contextlib

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    tctx = TransportToolContext.for_request(params, queue.put_nowait, loop)
    name = params.get('name')
    stream_id = uuid.uuid4().hex[:12]
    scope = getattr(mcp_session, 'session_id', None)

    def work():
        from sajha.core import mcp_cancellation
        token = tctx.activate()
        try:
            with contextlib.ExitStack() as stack:
                if sampled:
                    from sajha.ai.llm_tools.sampling import SessionSampler, bound
                    ctx = ToolCallContext(mcp_session, queue, _progress_token(params))
                    stack.enter_context(bound(SessionSampler(ctx, loop), name))
                if confirms:
                    from sajha.ai.llm_tools import confirmation
                    cctx = ToolCallContext(mcp_session, queue, _progress_token(params))
                    stack.enter_context(confirmation.bound(confirmation.SessionConfirmer(cctx, loop), name))
                if relayed:
                    from sajha.federation import relay
                    rctx = ToolCallContext(mcp_session, queue, _progress_token(params))
                    stack.enter_context(relay.bound(relay.ClientRelay(
                        rctx, loop, dict(mcp_session.client_capabilities or {})), name))
                stack.enter_context(mcp_cancellation.track(scope, body.get('id')))
                return handler.handle_request(body, session_data)
        finally:
            ModernToolContext.deactivate(token)

    async def events():
        counter = 0

        def next_id():
            nonlocal counter
            counter += 1
            return f"{stream_id}:{counter}"

        yield {'id': next_id(), 'data': ''}      # priming event (SEP-1699)
        task = asyncio.ensure_future(run_in_threadpool(work))
        try:
            while True:
                getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({getter, task}, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    yield {'id': next_id(), 'event': 'message', 'data': json.dumps(getter.result())}
                    continue
                getter.cancel()
                while not queue.empty():
                    yield {'id': next_id(), 'event': 'message', 'data': json.dumps(queue.get_nowait())}
                yield {'id': next_id(), 'event': 'message', 'data': json.dumps(task.result())}
                return
        finally:
            if not task.done():
                tctx.cancel()                    # the client went away: the tool sees is_cancelled()
                task.cancel()

    return EventSourceResponse(events())


# ── Streamable HTTP: DELETE /mcp ─────────────────────────────────

@router.delete('/mcp')
@router.delete('/api/mcp')
async def mcp_delete(request: Request, db: Session = Depends(get_db)):
    """Terminate an MCP session: 204 on success, 404 if unknown, 400 if no header."""
    from sajha.core.mcp_sessions import get_session_store
    from sajha.core.mcp_modern import is_modern_header
    err = _check_origin(request)
    if err is not None:
        return err
    if is_modern_header(request.headers):
        return _modern_405()
    _, err = await authorize_mcp(request, db, None)
    if err is not None:
        return err
    sid = request.headers.get(_SESSION_HEADER)
    if not sid:
        return _rpc_error(-32600, 'Mcp-Session-Id header required', 400)
    if not get_session_store().delete(sid):
        return _rpc_error(-32001, 'Session not found', 404)
    stream = _open_session_streams.get(sid)
    if stream is not None:
        stream.put_nowait(None)               # end the session's GET stream
    _release_subscriptions(sid)
    return Response(status_code=204)


# ── GET /mcp ─────────────────────────────────────────────────────

@router.get('/mcp')
@router.get('/mcp/sse')
async def mcp_sse(request: Request, db: Session = Depends(get_db)):
    """
    GET on the MCP endpoint.

    * Streamable HTTP clients (2025-03-26 and later) identify themselves with
      the Mcp-Session-Id and/or MCP-Protocol-Version header.  With a live
      session id and ``Accept: text/event-stream`` this opens the session's
      standalone server -> client stream, which carries
      ``notifications/{tools,prompts,resources}/list_changed`` from the change
      bus (one stream per session in this process: a second one is 409).
      Without a session id it answers 405 (unknown session id -> 404).
    * Requests without those headers (and every GET /mcp/sse) get the legacy
      2024-11-05 HTTP+SSE stream whose first event is ``endpoint``, so old
      clients keep working.
    """
    from sajha.core.mcp_modern import is_modern_header
    err = _check_origin(request)
    if err is not None:
        return err

    if request.url.path.rstrip('/') == '/mcp' and is_modern_header(request.headers):
        return _modern_405()

    if request.url.path.rstrip('/') == '/mcp' and (
            request.headers.get(_SESSION_HEADER) or request.headers.get(_VERSION_HEADER)):
        err = _check_protocol_header(request)
        if err is not None:
            return err
        session, err = _lookup_session(request)
        if err is not None:
            return err
        if session is None:
            return JSONResponse({'error': 'Method Not Allowed: the standalone server-to-client SSE '
                                          'stream needs an Mcp-Session-Id (initialize first)'},
                                status_code=405, headers={'Allow': 'POST, DELETE'})
        return await _session_stream(request, db, session)

    _, err = await authorize_mcp(request, db, None)
    if err is not None:
        return err
    release_session(db)     # the stream stays open for the connection's life: it holds no pool connection
    session_id = str(uuid.uuid4())
    sse_queue = _sse_relay.register(session_id)

    # Every connection is a new session with its own stream, so there is nothing to resume:
    # events carry ids but Last-Event-ID is not honoured (the legacy transport never had it).
    from sajha.core.mcp_2025_11_25 import SSEEventTracker
    tracker = SSEEventTracker()

    async def event_generator():
        forwarder = asyncio.create_task(forward_changes(sse_queue))
        try:
            # First event: tell the legacy client where to POST
            eid = tracker.next_id(session_id)
            endpoint_data = f'/mcp?session={session_id}'
            yield {
                'id': eid,
                'event': 'endpoint',
                'data': endpoint_data,
            }

            while True:
                if await request.is_disconnected():
                    break
                try:
                    notification = await asyncio.wait_for(sse_queue.get(), timeout=5)
                    eid = tracker.next_id(session_id)
                    data = json.dumps(notification)
                    yield {
                        'id': eid,
                        'event': 'message',
                        'data': data,
                    }
                except asyncio.TimeoutError:
                    _sse_relay.keepalive(session_id)
                    yield {'event': 'ping', 'data': ''}
        finally:
            forwarder.cancel()
            _sse_relay.unregister(session_id)

    return EventSourceResponse(event_generator())


_open_session_streams: dict = {}       # session id -> queue of its GET /mcp stream open in this process
_SESSION_STREAM_CHECK_SECONDS = 15.0


def _forward_resource_updates(queue: asyncio.Queue, session):
    """Copy notifications/resources/updated for the URIs this session subscribed to (resources/subscribe,
    the session's ``subscriptions``) into its GET stream's queue; returns the function that stops it.
    Subscriptions live with the session in this process."""
    from sajha.core.change_bus import RESOURCE_UPDATED, get_change_bus
    loop = asyncio.get_running_loop()

    def on_change(event):
        if event.kind == RESOURCE_UPDATED and event.uri in session.subscriptions:
            loop.call_soon_threadsafe(queue.put_nowait, event.notification())
    bus = get_change_bus()
    bus.add_listener(on_change)
    return lambda: bus.remove_listener(on_change)


def _release_subscriptions(sid: str) -> None:
    """A deleted session's subscriptions to proxied servers' resources end (sajha/federation)."""
    try:
        from sajha.federation.manager import get_federation
        fed = get_federation()
        if fed is not None:
            fed.release(f'session:{sid}')
    except Exception as e:
        logger.debug(f'releasing subscriptions of session {sid}: {e}')


async def _session_stream(request: Request, db, session):
    """The standalone GET /mcp SSE stream of a 2025-11-25 streamable-HTTP session: list_changed
    notifications from the change bus (every worker's, with a shared state store), and
    notifications/resources/updated for the URIs the session subscribed to (this worker's), until the
    client goes away or the session ends (DELETE /mcp or expiry).  No resumption: Last-Event-ID is ignored."""
    from sajha.core.mcp_sessions import get_session_store
    auth, err = await authorize_mcp(request, db, None)
    if err is not None:
        return err
    if 'text/event-stream' not in request.headers.get('accept', ''):
        return _rpc_error(-32600, 'GET /mcp opens an SSE stream: Accept must include text/event-stream', 406)
    caller = (auth.to_legacy_session() or {}).get('user_id')
    release_session(db)     # the stream stays open for the session's life: it holds no pool connection
    if session.user_id and session.user_id != caller:
        return _rpc_error(-32001, 'Session not found', 404)     # never attach to another user's session
    sid = session.session_id
    if sid in _open_session_streams:
        return _rpc_error(-32000, 'Conflict: this session already has an open SSE stream', 409)
    queue: asyncio.Queue = asyncio.Queue()
    _open_session_streams[sid] = queue
    stream_id = uuid.uuid4().hex[:12]

    async def events():
        forwarder = asyncio.create_task(forward_changes(queue))
        updates = _forward_resource_updates(queue, session)
        counter = 0
        try:
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=_SESSION_STREAM_CHECK_SECONDS)
                except asyncio.TimeoutError:
                    if get_session_store().get(sid) is None or await request.is_disconnected():
                        return
                    continue
                if message is None:            # the session was deleted
                    return
                counter += 1
                yield {'id': f'{stream_id}:{counter}', 'event': 'message', 'data': json.dumps(message)}
        finally:
            forwarder.cancel()
            updates()
            if _open_session_streams.get(sid) is queue:
                del _open_session_streams[sid]

    return EventSourceResponse(events(), ping=15)


@router.post('/mcp/message')
async def mcp_message(request: Request, db: Session = Depends(get_db)):
    """
    Backwards-compatible SSE message endpoint (2024-11-05 pattern).
    New clients should POST to /mcp directly.
    """
    from sajha.app import mcp_handler

    err = _check_origin(request)
    if err is not None:
        return err
    session_id = request.query_params.get('session')

    try:
        body = await request.json()
    except Exception as e:
        body = e
    method = body.get('method') if isinstance(body, dict) and isinstance(body.get('method'), str) else None
    auth, err = await authorize_mcp(request, db, method)
    if err is not None:
        return err
    session_data = auth.to_legacy_session()  # identity + tool policy (anonymous too)
    if isinstance(body, Exception):
        return JSONResponse({
            'jsonrpc': '2.0',
            'error': {'code': -32700, 'message': 'Parse error'},
        }, status_code=400)

    if not isinstance(body, dict):
        return _rpc_error(-32600, 'Invalid Request', 400)
    live = session_id if session_id and _sse_relay.exists(session_id) else None
    params = body.get('params') if isinstance(body.get('params'), dict) else {}
    if body.get('method') == 'notifications/cancelled' and live and 'id' not in body:
        from sajha.core import mcp_cancellation      # stop the named in-flight call of this SSE session
        mcp_cancellation.cancel(live, params.get('requestId'), params.get('reason'))
    if body.get('method') == 'tools/call' and live:
        # progress (a remote SAJHA Net tool's too) goes over the session's SSE stream
        from sajha.core.mcp_tool_context import call_with_events
        response = await call_with_events(lambda: mcp_handler.handle_request(body, session_data), params,
                                          lambda m: _sse_relay.deliver(live, m), live, body.get('id'))
    else:
        response = await run_in_threadpool(mcp_handler.handle_request, body, session_data)
    # Tool enable/disable/reload reach the SSE stream as notifications/tools/list_changed
    # through the change bus (registry -> forward_changes), not from here.
    if body.get('method') == 'initialize' and session_id and _sse_relay.exists(session_id):
        response = with_push_capabilities(response)
    return JSONResponse(response)


# ── Resources (new in v3) ────────────────────────────────────────

@router.post('/api/resources/list')
async def resources_list(request: Request, auth: AuthContext = Depends(require_auth)):
    """MCP resources/list — expose datasets, docs, tool catalog (counting only the tools
    this caller may see: the tools/list policy, sajha/auth/access.py)."""
    from sajha.app import tools_registry
    from sajha.auth.access import policy_for

    policy = policy_for(auth)
    resources = []

    # Tool catalog as a resource
    visible = [n for n in (tools_registry.tools if tools_registry else {}) if policy.can_see(n)]
    resources.append({
        'uri': 'sajha://tools/catalog',
        'name': 'Tool Catalog',
        'mimeType': 'application/json',
        'description': f'Catalog of {len(visible)} available MCP tools',
    })

    # Data directory files: the same listing and policy as MCP resources/list
    from sajha.auth.access import mcp_session_for
    from sajha.core import data_resources
    resources.extend(data_resources.list_resources(mcp_session_for(auth)))

    return JSONResponse({
        'jsonrpc': '2.0',
        'result': {'resources': resources},
    })


@router.post('/api/resources/read')
async def resources_read(request: Request, auth: AuthContext = Depends(require_auth)):
    """MCP resources/read — read a resource by URI (the tool catalog holds only the tools
    this caller may see)."""
    from sajha.app import tools_registry
    from sajha.auth.access import policy_for

    body = await request.json()
    uri = body.get('params', {}).get('uri', '')

    if uri == 'sajha://tools/catalog':
        policy = policy_for(auth)
        tools = tools_registry.get_all_tools() if tools_registry else []
        tools = [t for t in tools if policy.can_see(t.get('name'))]
        return JSONResponse({
            'jsonrpc': '2.0',
            'result': {
                'contents': [{
                    'uri': uri,
                    'mimeType': 'application/json',
                    'text': json.dumps(tools, indent=2),
                }]
            },
        })

    if isinstance(uri, str) and uri.startswith('sajha://data/'):
        # the same reader, path-traversal guard and policy as MCP resources/read
        from sajha.auth.access import mcp_session_for
        from sajha.core import data_resources
        try:
            result = data_resources.read_resource(uri, mcp_session_for(auth))
        except Exception as e:
            return JSONResponse({'jsonrpc': '2.0',
                                 'error': {'code': -32603, 'message': f'Error reading resource: {e}'}})
        if result is not None:
            return JSONResponse({'jsonrpc': '2.0', 'result': result})
        return JSONResponse({'jsonrpc': '2.0',
                             'error': {'code': -32002, 'message': 'Resource not found',
                                       'data': {'uri': uri}}})

    return JSONResponse({
        'jsonrpc': '2.0',
        'error': {'code': -32602, 'message': f'Unknown resource: {uri}'},
    })


# ── Completion (new in v3) ───────────────────────────────────────

@router.post('/api/completion/complete')
async def completion_complete(request: Request, auth: AuthContext = Depends(require_auth)):
    """MCP completion/complete — argument auto-complete for tools the caller may see."""
    from sajha.app import tools_registry
    from sajha.auth.access import policy_for

    body = await request.json()
    params = body.get('params', {})
    ref = params.get('ref', {})

    if ref.get('type') == 'ref/tool':
        tool_name = ref.get('name', '')
        argument_name = params.get('argument', {}).get('name', '')
        partial_value = params.get('argument', {}).get('value', '')

        tool = tools_registry.get_tool(tool_name) if tools_registry else None
        if tool and policy_for(auth).can_see(tool_name):
            schema = tool.input_schema
            prop = schema.get('properties', {}).get(argument_name, {})
            # If the property has an enum, filter by partial match
            if 'enum' in prop:
                matches = [v for v in prop['enum'] if partial_value.lower() in v.lower()]
                return JSONResponse({
                    'jsonrpc': '2.0',
                    'result': {
                        'completion': {
                            'values': matches[:10],
                            'hasMore': len(matches) > 10,
                        }
                    },
                })

    return JSONResponse({
        'jsonrpc': '2.0',
        'result': {'completion': {'values': [], 'hasMore': False}},
    })


# ── Logging (new in v3) ─────────────────────────────────────────

@router.post('/api/logging/setLevel')
async def logging_set_level(request: Request, auth: AuthContext = Depends(require_admin)):
    """Change the server's root log level (admin only)."""
    body = await request.json()
    level = body.get('params', {}).get('level', 'info').upper()

    valid_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
    if level not in valid_levels:
        return JSONResponse({
            'jsonrpc': '2.0',
            'error': {'code': -32602, 'message': f'Invalid level: {level}'},
        })

    logging.getLogger().setLevel(getattr(logging, level))
    logger.info(f'Log level changed to {level}')

    return JSONResponse({'jsonrpc': '2.0', 'result': {}})
