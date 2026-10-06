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

from sajha.db.engine import get_db
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
    channel (2024-11-05 HTTP+SSE stream, WebSocket): those receive
    list_changed notifications from the change bus, so they advertise
    listChanged.  Streamable-HTTP 2025-11-25 sessions do not (SAJHA offers no
    GET stream there), so the shared handler capabilities keep it false.
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

    # Notification: no id -> 202, no body
    if body.get('jsonrpc') == '2.0' and isinstance(body.get('method'), str) and 'id' not in body:
        await run_in_threadpool(mcp_handler.handle_request, body, session_data)
        if mcp_session and body['method'] in ('notifications/initialized', 'initialized'):
            mcp_session.initialized = True
        return Response(status_code=202)

    method = body.get('method')
    params = body.get('params') if isinstance(body.get('params'), dict) else {}

    # Tools that interact with the client while running (conformance fixtures)
    if method == 'tools/call':
        from sajha.core.mcp_conformance_fixtures import get_conformance_fixtures
        fixtures = get_conformance_fixtures()
        if fixtures and fixtures.is_async_tool(params.get('name', '')):
            return await _stream_tool_call(request, body, params, fixtures, mcp_session)

    response = await run_in_threadpool(mcp_handler.handle_request, body, session_data)

    # Legacy 2024-11-05 HTTP+SSE client: the response travels over its SSE stream
    legacy_sid = request.query_params.get('session')
    if legacy_sid and _sse_relay.exists(legacy_sid):
        if method == 'initialize':
            response = with_push_capabilities(response)
        await _sse_relay.deliver(legacy_sid, response)
        return Response(status_code=202)

    headers = {}
    if method == 'initialize' and isinstance(response, dict) and 'result' in response:
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
    return Response(status_code=204)


# ── GET /mcp ─────────────────────────────────────────────────────

@router.get('/mcp')
@router.get('/mcp/sse')
async def mcp_sse(request: Request, db: Session = Depends(get_db)):
    """
    GET on the MCP endpoint.

    * Streamable HTTP clients (2025-03-26 and later) identify themselves with
      the Mcp-Session-Id and/or MCP-Protocol-Version header.  SAJHA does not
      push unsolicited server -> client messages, so — as the spec allows —
      it answers 405 Method Not Allowed instead of opening an idle stream
      (unknown session id -> 404).
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
        _, err = _lookup_session(request)
        if err is not None:
            return err
        return JSONResponse({'error': 'Method Not Allowed: this server does not offer a '
                                      'standalone server-to-client SSE stream'},
                            status_code=405, headers={'Allow': 'POST, DELETE'})

    _, err = await authorize_mcp(request, db, None)
    if err is not None:
        return err
    session_id = str(uuid.uuid4())
    sse_queue = _sse_relay.register(session_id)

    from sajha.core.mcp_2025_11_25 import SSEEventTracker
    tracker = SSEEventTracker()
    last_event_id = request.headers.get('Last-Event-ID')

    async def event_generator():
        forwarder = asyncio.create_task(forward_changes(sse_queue))
        try:
            if last_event_id:
                for missed in tracker.get_events_after(last_event_id):
                    yield {'id': missed['id'], 'event': missed['event'], 'data': missed['data']}

            # First event: tell the legacy client where to POST
            eid = tracker.next_id(session_id)
            endpoint_data = f'/mcp?session={session_id}'
            tracker.record_event(eid, 'endpoint', endpoint_data)
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
                    tracker.record_event(eid, 'message', data)
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
    response = await run_in_threadpool(mcp_handler.handle_request, body, session_data)
    # Tool enable/disable/reload reach the SSE stream as notifications/tools/list_changed
    # through the change bus (registry -> forward_changes), not from here.
    if body.get('method') == 'initialize' and session_id and _sse_relay.exists(session_id):
        response = with_push_capabilities(response)
    return JSONResponse(response)


# ── Resources (new in v3) ────────────────────────────────────────

@router.post('/api/resources/list')
async def resources_list(request: Request, auth: AuthContext = Depends(require_auth)):
    """MCP resources/list — expose datasets, docs, tool catalog."""
    from sajha.app import tools_registry

    resources = []

    # Tool catalog as a resource
    resources.append({
        'uri': 'sajha://tools/catalog',
        'name': 'Tool Catalog',
        'mimeType': 'application/json',
        'description': f'Catalog of {len(tools_registry.tools)} available MCP tools',
    })

    # Data directory files
    import os
    data_dir = 'data/duckdb'
    if os.path.isdir(data_dir):
        for fname in os.listdir(data_dir):
            if fname.endswith(('.csv', '.parquet', '.json')):
                resources.append({
                    'uri': f'sajha://data/{fname}',
                    'name': fname,
                    'mimeType': 'application/octet-stream',
                    'description': f'Data file: {fname}',
                })

    return JSONResponse({
        'jsonrpc': '2.0',
        'result': {'resources': resources},
    })


@router.post('/api/resources/read')
async def resources_read(request: Request, auth: AuthContext = Depends(require_auth)):
    """MCP resources/read — read a resource by URI."""
    from sajha.app import tools_registry

    body = await request.json()
    uri = body.get('params', {}).get('uri', '')

    if uri == 'sajha://tools/catalog':
        tools = tools_registry.get_all_tools() if tools_registry else []
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

    return JSONResponse({
        'jsonrpc': '2.0',
        'error': {'code': -32602, 'message': f'Unknown resource: {uri}'},
    })


# ── Completion (new in v3) ───────────────────────────────────────

@router.post('/api/completion/complete')
async def completion_complete(request: Request, auth: AuthContext = Depends(require_auth)):
    """MCP completion/complete — argument auto-complete for tools."""
    from sajha.app import tools_registry

    body = await request.json()
    params = body.get('params', {})
    ref = params.get('ref', {})

    if ref.get('type') == 'ref/tool':
        tool_name = ref.get('name', '')
        argument_name = params.get('argument', {}).get('name', '')
        partial_value = params.get('argument', {}).get('value', '')

        tool = tools_registry.get_tool(tool_name) if tools_registry else None
        if tool:
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
