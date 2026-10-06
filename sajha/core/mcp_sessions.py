"""
MCP Streamable HTTP session store (MCP 2025-11-25, basic/transports).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A session is created when a client POSTs ``initialize`` to ``/mcp``; its id
is returned in the ``Mcp-Session-Id`` response header.  Subsequent requests
that carry the header must name a live session (otherwise HTTP 404) and
``DELETE /mcp`` ends it.

The store also routes server -> client JSON-RPC requests (sampling,
elicitation) made while a tool call is streaming its response over SSE:
the server sends the request on the open stream and the client POSTs its
JSON-RPC response back to ``/mcp``, where it resolves the waiting future.

Sessions live in process memory.  After a restart clients receive 404 for
their old session id and, per the spec, start a new session by
re-initializing.
"""

import asyncio
import itertools
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Idle sessions are dropped after this many seconds.
SESSION_IDLE_TTL_SECONDS = 24 * 3600
MAX_SESSIONS = 10000


@dataclass
class MCPSession:
    session_id: str
    protocol_version: str
    client_info: Dict[str, Any] = field(default_factory=dict)
    client_capabilities: Dict[str, Any] = field(default_factory=dict)
    user_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    initialized: bool = False
    subscriptions: set = field(default_factory=set)
    # server -> client request id -> Future resolved by the client's response
    pending: Dict[Any, asyncio.Future] = field(default_factory=dict)

    def touch(self):
        self.last_seen = time.time()

    def supports(self, capability: str) -> bool:
        return capability in (self.client_capabilities or {})


class MCPSessionStore:
    def __init__(self):
        self._sessions: Dict[str, MCPSession] = {}
        self._lock = threading.Lock()
        self._request_ids = itertools.count(1)

    def create(self, protocol_version: str, client_info: Dict = None,
               client_capabilities: Dict = None, user_id: str = None) -> MCPSession:
        session = MCPSession(
            session_id=uuid.uuid4().hex,
            protocol_version=protocol_version,
            client_info=client_info or {},
            client_capabilities=client_capabilities or {},
            user_id=user_id,
        )
        with self._lock:
            self._expire_locked()
            if len(self._sessions) >= MAX_SESSIONS:
                oldest = min(self._sessions.values(), key=lambda s: s.last_seen)
                self._sessions.pop(oldest.session_id, None)
            self._sessions[session.session_id] = session
        logger.info(f"MCP session created: {session.session_id} "
                    f"(client={session.client_info.get('name', '?')}, protocol={protocol_version})")
        return session

    def get(self, session_id: Optional[str]) -> Optional[MCPSession]:
        if not session_id:
            return None
        with self._lock:
            session = self._sessions.get(session_id)
            if session and time.time() - session.last_seen > SESSION_IDLE_TTL_SECONDS:
                self._sessions.pop(session_id, None)
                session = None
        if session:
            session.touch()
        return session

    def delete(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if not session:
            return False
        for fut in session.pending.values():
            if not fut.done():
                fut.cancel()
        logger.info(f"MCP session terminated: {session_id}")
        return True

    def __len__(self):
        return len(self._sessions)

    def _expire_locked(self):
        now = time.time()
        for sid in [s for s, v in self._sessions.items()
                    if now - v.last_seen > SESSION_IDLE_TTL_SECONDS]:
            self._sessions.pop(sid, None)

    # ── server -> client requests ────────────────────────────────

    def new_request_id(self) -> str:
        return f"srv-{next(self._request_ids)}"

    def resolve_response(self, session: Optional[MCPSession], message: Dict) -> bool:
        """Deliver a client's JSON-RPC response to the waiting server request."""
        rid = message.get('id')
        candidates = [session] if session else list(self._sessions.values())
        for s in candidates:
            fut = s.pending.pop(rid, None) if s else None
            if fut is not None:
                if not fut.done():
                    fut.get_loop().call_soon_threadsafe(_set_future, fut, message)
                return True
        return False


def _set_future(fut: asyncio.Future, value):
    if not fut.done():
        fut.set_result(value)


_store = MCPSessionStore()


def get_session_store() -> MCPSessionStore:
    return _store


class ToolCallContext:
    """
    Gives an async tool a way to talk to the client while its tools/call
    response is being streamed over SSE: notifications (logging, progress)
    and server -> client requests (sampling/createMessage, elicitation/create).
    """

    def __init__(self, session: Optional[MCPSession], queue: Optional[asyncio.Queue],
                 progress_token: Any = None, store: MCPSessionStore = None):
        # queue is None when the client did not accept an SSE response:
        # notifications are then dropped and server -> client requests fail.
        self.session = session
        self.queue = queue
        self.progress_token = progress_token
        self.store = store or _store

    async def notify(self, method: str, params: Dict[str, Any]):
        if self.queue is None:
            return
        await self.queue.put({'jsonrpc': '2.0', 'method': method, 'params': params})

    async def log(self, level: str, data: Any, logger_name: str = None):
        params = {'level': level, 'data': data}
        if logger_name:
            params['logger'] = logger_name
        await self.notify('notifications/message', params)

    async def progress(self, progress: float, total: float = None, message: str = None):
        if self.progress_token is None:
            return
        params = {'progressToken': self.progress_token, 'progress': progress}
        if total is not None:
            params['total'] = total
        if message:
            params['message'] = message
        await self.notify('notifications/progress', params)

    def client_supports(self, capability: str) -> bool:
        return bool(self.session and self.session.supports(capability))

    async def request(self, method: str, params: Dict[str, Any], timeout: float = 120.0) -> Dict:
        """Send a request to the client and wait for its response's result."""
        if self.session is None:
            raise RuntimeError(f"{method} requires an MCP session (initialize first)")
        if self.queue is None:
            raise RuntimeError(f"{method} requires an SSE response stream (Accept: text/event-stream)")
        rid = self.store.new_request_id()
        fut = asyncio.get_running_loop().create_future()
        self.session.pending[rid] = fut
        await self.queue.put({'jsonrpc': '2.0', 'id': rid, 'method': method, 'params': params})
        try:
            message = await asyncio.wait_for(fut, timeout)
        finally:
            self.session.pending.pop(rid, None)
        if 'error' in message:
            err = message['error'] or {}
            raise RuntimeError(f"Client returned error for {method}: {err.get('message', err)}")
        return message.get('result') or {}
