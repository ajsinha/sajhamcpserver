"""
SAJHA MCP Server v3 — WebSocket Transport
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Bidirectional WebSocket transport for MCP JSON-RPC 2.0.

Supports:
  - Full-duplex communication (server can push notifications anytime)
  - Authentication via query params (?token=... or ?api_key=...)
  - Same MCPHandler as HTTP POST and SSE transports
  - Session lifecycle: connect → authenticate → exchange → disconnect
  - Heartbeat via WebSocket ping/pong frames
  - Batch JSON-RPC requests
  - Server-initiated notifications (tools/list_changed, progress, log)

Usage:
  Client connects to ws://host:3002/mcp/ws?token=<jwt>
  or:  ws://host:3002/mcp/ws?api_key=<key>

  Then sends/receives JSON-RPC 2.0 messages as text frames:
    → {"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}
    ← {"jsonrpc":"2.0","id":1,"result":{...}}
    ← {"jsonrpc":"2.0","method":"notifications/tools/list_changed"}
"""

import json
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session

from sajha.db.engine import get_db_session
from sajha.auth import AuthManager, AuthContext, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(tags=['mcp-websocket'])


# ── Active WebSocket sessions ────────────────────────────────

class WSSession:
    """Represents an active WebSocket MCP session."""

    __slots__ = ('id', 'ws', 'user_id', 'auth_context', 'session_data',
                 'connected_at', 'last_activity', 'initialized',
                 '_notification_queue')

    def __init__(self, ws: WebSocket, session_id: str):
        self.id = session_id
        self.ws = ws
        self.user_id: str = 'anonymous'
        self.auth_context = None
        self.session_data: Optional[Dict] = None
        self.connected_at = datetime.utcnow()
        self.last_activity = datetime.utcnow()
        self.initialized = False
        self._notification_queue: asyncio.Queue = asyncio.Queue()

    async def send(self, message: Dict):
        """Send a JSON-RPC message to the client."""
        await self.ws.send_text(json.dumps(message, default=str))
        self.last_activity = datetime.utcnow()

    async def send_notification(self, method: str, params: Dict = None):
        """Send a server-initiated notification (no id, no response expected)."""
        msg = {'jsonrpc': '2.0', 'method': method}
        if params:
            msg['params'] = params
        await self.send(msg)

    def to_dict(self) -> Dict:
        return {
            'session_id': self.id,
            'user_id': self.user_id,
            'connected_at': self.connected_at.isoformat(),
            'last_activity': self.last_activity.isoformat(),
            'initialized': self.initialized,
        }


_ws_sessions: Dict[str, WSSession] = {}


def get_active_sessions() -> list:
    """Return info about all active WebSocket sessions."""
    return [s.to_dict() for s in _ws_sessions.values()]


async def broadcast_notification(method: str, params: Dict = None):
    """Send a notification to ALL active WebSocket sessions.
    Called by hot-reload, tool registry changes, etc.
    """
    dead = []
    for sid, session in _ws_sessions.items():
        try:
            await session.send_notification(method, params)
        except Exception as e:
            dead.append(sid)
    for sid in dead:
        _ws_sessions.pop(sid, None)


# ── WebSocket endpoint ───────────────────────────────────────

@router.websocket('/mcp/ws')
async def mcp_websocket(ws: WebSocket):
    """
    WebSocket transport for MCP JSON-RPC 2.0.

    Authentication: pass ?token=<jwt> or ?api_key=<key> as query params.
    Protocol: send/receive JSON-RPC 2.0 text frames.
    """
    from sajha.app import mcp_handler
    from sajha.policy.context import set_source
    set_source('websocket')      # policy rules can match sources: [websocket]; this connection's context only

    # The /mcp Origin allow-list (DNS rebinding, cross-site socket hijacking): a browser page from
    # another origin may not open the socket (mcp.allowed_origins; loopback and no Origin pass)
    from sajha.core.mcp_2025_11_25 import validate_origin
    if not validate_origin(ws.headers.get('origin')):
        logger.warning(f"WebSocket refused: Origin {ws.headers.get('origin')!r} not allowed")
        await ws.close(code=1008, reason='Origin not allowed')
        return

    await ws.accept()
    session_id = str(uuid.uuid4())
    session = WSSession(ws, session_id)

    # ── Authenticate from query params ──
    token = ws.query_params.get('token', '')
    api_key = ws.query_params.get('api_key', '')

    db = get_db_session()
    try:
        if token:
            auth = AuthManager.authenticate_jwt(db, token)
        elif api_key:
            auth = AuthManager.authenticate_apikey(db, api_key)
        else:
            auth = None

        if auth and auth.authenticated:
            session.user_id = auth.user_id
            session.auth_context = auth
            # identity + tool policy: the same per-tool access rules as the REST API
            session.session_data = auth.to_legacy_session()
    except Exception as e:
        logger.warning(f"WS auth failed: {e}", exc_info=True)
    finally:
        db.close()

    from sajha.auth.oauth.settings import auth_mode
    from sajha.auth.access import anonymous_enabled, mcp_session_for
    if session.auth_context is None:
        if token or api_key or auth_mode() == 'required' or not anonymous_enabled():
            # invalid credentials, mcp.auth.mode=required or mcp.anonymous.enabled=false:
            # this transport takes SAJHA JWTs / API keys only (no OAuth flow)
            await ws.close(code=1008, reason='Authentication required')
            return
        session.session_data = mcp_session_for(None)   # the anonymous tool policy

    _ws_sessions[session_id] = session
    logger.info(f"WebSocket connected: {session_id} (user={session.user_id})")
    forwarder = asyncio.create_task(_forward_changes(session))

    try:
        while True:
            # Receive text frame (JSON-RPC message)
            raw = await ws.receive_text()
            session.last_activity = datetime.utcnow()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await session.send({
                    'jsonrpc': '2.0',
                    'error': {'code': -32700, 'message': 'Parse error: invalid JSON'},
                    'id': None,
                })
                continue

            # ── Batch request ──
            if isinstance(data, list):
                responses = mcp_handler.handle_batch_request(data, session.session_data)
                for resp in responses:
                    await session.send(resp)
                continue

            # ── Single request ──
            method = data.get('method', '')

            # Track initialization
            if method == 'initialize':
                session.initialized = True

            # Handle via the same MCPHandler used by HTTP POST and SSE
            response = mcp_handler.handle_request(data, session.session_data)

            # Send response (skip for notifications — requests without 'id')
            if 'id' in data:
                if method == 'initialize':
                    # this transport pushes list_changed (change bus -> _forward_changes)
                    from sajha.routes.mcp_routes import with_push_capabilities
                    response = with_push_capabilities(response)
                await session.send(response)
            # Tool enable/disable/reload -> notifications/tools/list_changed arrives
            # through the change bus (_forward_changes), for every connected client.

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id} (user={session.user_id})")
    except Exception as e:
        logger.error(f"WebSocket error: {session_id}: {e}", exc_info=True)
        try:
            await ws.close(code=1011, reason=str(e)[:120])
        except Exception as e:
            logger.warning(f"Error handled: {e}", exc_info=True)
            pass
    finally:
        forwarder.cancel()
        _ws_sessions.pop(session_id, None)


async def _forward_changes(session: 'WSSession'):
    """Deliver change-bus events (tool/prompt/resource list changes) to one WebSocket client."""
    from sajha.core.change_bus import get_change_bus, TOOLS, PROMPTS, RESOURCES
    sub = get_change_bus().subscribe({TOOLS, PROMPTS, RESOURCES})
    try:
        while True:
            event = await sub.get()
            if event is None:
                return
            message = event.notification()
            try:
                await session.send_notification(message['method'], message.get('params'))
            except Exception:
                return          # socket gone; the receive loop cleans up
    finally:
        sub.close()


# ── Admin: Active sessions API ───────────────────────────────

@router.get('/api/ws/sessions')
async def api_ws_sessions(auth: AuthContext = Depends(require_admin)):
    """List active WebSocket sessions (admin diagnostic)."""
    return {
        'active_sessions': get_active_sessions(),
        'count': len(_ws_sessions),
    }


# ── Hook: call this from hot-reload callbacks ─────────────────

async def notify_tools_changed():
    """Notify all WebSocket clients that tools/list has changed.
    Call from hot-reload, composite tool save, tool enable/disable.
    """
    await broadcast_notification('notifications/tools/list_changed')


async def notify_resources_changed():
    """Notify all WebSocket clients that resources have changed."""
    await broadcast_notification('notifications/resources/list_changed')
