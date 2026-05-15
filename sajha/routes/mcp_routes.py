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

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from sajha.db.engine import get_db
from sajha.auth import AuthManager, AuthContext

logger = logging.getLogger(__name__)
router = APIRouter(tags=['mcp'])

# ── Active SSE sessions ──────────────────────────────────────────
_sse_sessions: dict[str, asyncio.Queue] = {}


@router.get('/mcp')
@router.get('/mcp/sse')
async def mcp_sse(request: Request, db: Session = Depends(get_db)):
    """
    MCP 2025-11-25 Streamable HTTP transport — GET endpoint.

    Per spec: "The server MUST provide a single HTTP endpoint path
    that supports both POST and GET methods."

    GET /mcp opens an SSE stream for server → client notifications.
    POST /mcp sends JSON-RPC requests (handled in api_routes.py).

    The /mcp/sse path is kept for backwards compatibility with
    2024-11-05 HTTP+SSE clients.
    """
    # MCP 2025-11-25 Minor 3: Validate Origin header
    from sajha.core.mcp_2025_11_25 import validate_origin
    origin = request.headers.get('origin')
    if not validate_origin(origin):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Forbidden: invalid Origin"}, status_code=403)

    auth = AuthManager.authenticate_request(request, db)
    session_id = str(uuid.uuid4())
    _sse_sessions[session_id] = asyncio.Queue()

    # MCP 2025-11-25 Minor 7: SSE event IDs for stream resumption
    from sajha.core.mcp_2025_11_25 import SSEEventTracker
    tracker = SSEEventTracker()
    last_event_id = request.headers.get('Last-Event-ID')

    async def event_generator():
        try:
            # Replay missed events if client reconnects with Last-Event-ID
            if last_event_id:
                for missed in tracker.get_events_after(last_event_id):
                    yield {'id': missed['id'], 'event': missed['event'], 'data': missed['data']}

            # First event: tell the client where to POST
            # 2025-11-25: POST to same /mcp endpoint (Streamable HTTP)
            # Also include session for backwards compat with /mcp/message
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
                    notification = _sse_sessions[session_id].get_nowait()
                    eid = tracker.next_id(session_id)
                    data = json.dumps(notification)
                    tracker.record_event(eid, 'message', data)
                    yield {
                        'id': eid,
                        'event': 'message',
                        'data': data,
                    }
                except asyncio.QueueEmpty:
                    # Keep-alive
                    yield {'event': 'ping', 'data': ''}
                    await asyncio.sleep(5)
        finally:
            _sse_sessions.pop(session_id, None)

    return EventSourceResponse(event_generator())


@router.post('/mcp/message')
async def mcp_message(request: Request, db: Session = Depends(get_db)):
    """
    Backwards-compatible SSE message endpoint (2024-11-05 pattern).
    New clients should POST to /mcp directly.
    """
    from sajha.app import mcp_handler

    session_id = request.query_params.get('session')
    auth = AuthManager.authenticate_request(request, db)
    session_data = auth.to_legacy_session() if auth.authenticated else None

    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({
            'jsonrpc': '2.0',
            'error': {'code': -32700, 'message': 'Parse error'},
        }, status_code=400)

    response = mcp_handler.handle_request(body, session_data)

    # If a notification should go to the SSE stream
    if session_id and session_id in _sse_sessions:
        # Push list_changed notification if tools were modified
        method = body.get('method', '')
        if 'enable' in method or 'disable' in method or 'reload' in method:
            await _sse_sessions[session_id].put({
                'jsonrpc': '2.0',
                'method': 'notifications/tools/list_changed',
            })

    return JSONResponse(response)


# ── Resources (new in v3) ────────────────────────────────────────

@router.post('/api/resources/list')
async def resources_list(request: Request):
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
async def resources_read(request: Request):
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
async def completion_complete(request: Request):
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
async def logging_set_level(request: Request):
    """MCP logging/setLevel — dynamically adjust server log level."""
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
