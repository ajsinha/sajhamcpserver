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
from sajha.auth import AuthManager

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

    await ws.accept()
    session_id = str(uuid.uuid4())
    session = WSSession(ws, session_id)

    # ── Authenticate from query params ──
    token = ws.query_params.get('token', '')
    api_key = ws.query_params.get('api_key', '')

    db = get_db_session()
    try:
        if token:
            auth = AuthManager.authenticate_token(token, db)
        elif api_key:
            auth = AuthManager.authenticate_api_key(api_key, db)
        else:
            auth = None

        if auth and auth.authenticated:
            session.user_id = auth.user_id
            session.auth_context = auth
            session.session_data = auth.to_legacy_session()
        else:
            session.session_data = None
    except Exception as e:
        logger.warning(f"WS auth failed: {e}", exc_info=True)
        session.session_data = None
    finally:
        db.close()

    _ws_sessions[session_id] = session
    logger.info(f"WebSocket connected: {session_id} (user={session.user_id})")

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
                await session.send(response)

            # Push list_changed if tool state was modified
            if 'enable' in method or 'disable' in method or 'reload' in method:
                await session.send_notification(
                    'notifications/tools/list_changed')

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
        _ws_sessions.pop(session_id, None)


# ── Admin: Active sessions API ───────────────────────────────

@router.get('/api/ws/sessions')
async def api_ws_sessions():
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
