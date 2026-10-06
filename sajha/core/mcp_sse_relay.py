"""
Legacy 2024-11-05 HTTP+SSE session queues, relayed between workers.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A legacy client opens ``GET /mcp/sse`` (one worker holds that stream and its
queue) and then POSTs requests to ``/mcp?session=<id>``; the responses travel
back over the stream.  With several workers the POST may land elsewhere, so:

* the stream's worker registers the session id in the shared state store
  (``mcp:sse:<id>``, TTL refreshed while the stream is open);
* a worker that receives a POST for an id it does not hold publishes the
  response on the ``mcp.sse`` channel, and the holding worker puts it on the
  stream's queue.

With the memory backend (no store attached) this is exactly the old
in-process dictionary.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_KEY = "mcp:sse:"
_CHANNEL = "mcp.sse"
_TTL = 120.0

_queues: Dict[str, asyncio.Queue] = {}
_loops: Dict[str, asyncio.AbstractEventLoop] = {}
_refreshed: Dict[str, float] = {}
_lock = threading.Lock()
_store = None
_unsubscribe = None


def attach_store(store) -> None:
    global _store, _unsubscribe
    if _store is store:
        return
    if _unsubscribe:
        _unsubscribe()
    _store = store
    _unsubscribe = store.subscribe(_CHANNEL, _on_message)


def detach_store() -> None:
    global _store, _unsubscribe
    if _unsubscribe:
        _unsubscribe()
    _store, _unsubscribe = None, None


def _on_message(message: Dict[str, Any]) -> None:
    sid = message.get("session_id")
    with _lock:
        queue, loop = _queues.get(sid), _loops.get(sid)
    if queue is not None and loop is not None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, message.get("message"))
        except RuntimeError:
            pass


def register(session_id: str) -> asyncio.Queue:
    """Open a local queue for a stream (call on the stream's event loop)."""
    queue: asyncio.Queue = asyncio.Queue()
    with _lock:
        _queues[session_id] = queue
        _loops[session_id] = asyncio.get_running_loop()
    if _store is not None:
        _store.set(_KEY + session_id, {"open": True}, ttl=_TTL)
        _refreshed[session_id] = time.time()
    return queue


def keepalive(session_id: str) -> None:
    """Slide the registration TTL while the stream is open."""
    if _store is not None and time.time() - _refreshed.get(session_id, 0) > _TTL / 3:
        _store.set(_KEY + session_id, {"open": True}, ttl=_TTL)
        _refreshed[session_id] = time.time()


def unregister(session_id: str) -> None:
    with _lock:
        _queues.pop(session_id, None)
        _loops.pop(session_id, None)
    _refreshed.pop(session_id, None)
    if _store is not None:
        try:
            _store.delete(_KEY + session_id)
        except Exception as e:
            logger.debug(f"sse unregister: {e}")


def local_queue(session_id: Optional[str]) -> Optional[asyncio.Queue]:
    with _lock:
        return _queues.get(session_id) if session_id else None


def exists(session_id: Optional[str]) -> bool:
    """A stream with this id is open on this worker or (shared store) on another one."""
    if not session_id:
        return False
    if local_queue(session_id) is not None:
        return True
    return _store is not None and _store.get(_KEY + session_id) is not None


async def deliver(session_id: str, message: Any) -> bool:
    """Put ``message`` on the session's stream, wherever it is open."""
    queue = local_queue(session_id)
    if queue is not None:
        await queue.put(message)
        return True
    if _store is not None and _store.get(_KEY + session_id) is not None:
        _store.publish(_CHANNEL, {"session_id": session_id, "message": message})
        return True
    return False
