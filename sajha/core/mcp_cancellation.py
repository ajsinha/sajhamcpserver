"""
SAJHA MCP Server — cancellation of in-flight 2025-11-25 requests.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

On the 2025-11-25 era a client cancels a request it sent with ``notifications/cancelled``
naming the request id. The request runs in a worker thread, so the notification cannot stop
it; it sets a flag the running code checks instead:

* the transport wraps each in-flight ``tools/call`` in ``track(scope, request_id)`` (scope:
  the MCP session id, or the stdio connection), which makes the flag the current one for
  that call (a context variable, inherited by the worker thread);
* ``cancel(scope, request_id)`` sets it, on this worker or, with a shared state store
  (redis | database), on whichever worker runs the request;
* ``is_cancelled()`` reads it. Federation polls it while it waits for an upstream and, once
  set, cancels the upstream call, which sends the upstream its own ``notifications/cancelled``
  (2025-11-25) or closes the request's stream (2026-07-28).

The 2026-07-28 era needs none of this: a dropped response stream cancels the request
(``ModernToolContext.cancel``). Design: docs/architecture/Federation.md (Cancellation).
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import threading
from typing import Any, Dict, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)

_CHANNEL = 'mcp.cancel'
_current: contextvars.ContextVar[Optional[threading.Event]] = \
    contextvars.ContextVar('sajha_mcp_cancel', default=None)
_inflight: Dict[Tuple[str, str], threading.Event] = {}
_lock = threading.Lock()
_relay = None
_unsubscribe = None


def _key(scope: Any, request_id: Any) -> Tuple[str, str]:
    # JSON-RPC ids compare by type and value: "1" and 1 are different requests
    return str(scope), json.dumps(request_id, sort_keys=True, default=str)


@contextlib.contextmanager
def track(scope: Any, request_id: Any) -> Iterator[threading.Event]:
    """Register an in-flight request and make its cancellation flag the current one."""
    event = threading.Event()
    if scope is None or request_id is None:
        token = _current.set(event)
        try:
            yield event
        finally:
            _current.reset(token)
        return
    key = _key(scope, request_id)
    _attach()
    with _lock:
        _inflight[key] = event
    token = _current.set(event)
    try:
        yield event
    finally:
        _current.reset(token)
        with _lock:
            if _inflight.get(key) is event:
                _inflight.pop(key, None)


def cancel(scope: Any, request_id: Any, reason: Optional[str] = None) -> bool:
    """Flag the request as cancelled. True when it runs on this worker; otherwise the cancel is
    relayed to the other workers when the state store is shared (unknown ids are ignored, as
    the specification allows)."""
    if scope is None or request_id is None:
        return False
    if _cancel_local(_key(scope, request_id)):
        logger.info(f'request {request_id!r} cancelled by the client' + (f': {reason}' if reason else ''))
        return True
    try:
        from sajha.core.state import get_state_store
        store = get_state_store()
        if store.shared:
            store.publish(_CHANNEL, {'op': 'cancel', 'scope': str(scope),
                                     'id': json.dumps(request_id, sort_keys=True, default=str)})
    except Exception as e:
        logger.debug(f'cancel relay: {e}')
    return False


def _cancel_local(key: Tuple[str, str]) -> bool:
    with _lock:
        event = _inflight.get(key)
    if event is None:
        return False
    event.set()
    return True


def is_cancelled() -> bool:
    """True once the current 2025-11-25 request was cancelled by its client."""
    event = _current.get()
    return bool(event is not None and event.is_set())


def _attach() -> None:
    """Listen for cancels relayed from other workers (shared state store only)."""
    global _relay, _unsubscribe
    try:
        from sajha.core.state import get_state_store
        store = get_state_store()
    except Exception:
        return
    if not getattr(store, 'shared', False) or _relay is store:
        return
    with _lock:
        if _relay is store:
            return
        if _unsubscribe:
            try:
                _unsubscribe()
            except Exception:
                pass
        _relay = store
        _unsubscribe = store.subscribe(_CHANNEL, _on_message)


def _on_message(message: Dict[str, Any]) -> None:
    if isinstance(message, dict) and message.get('op') == 'cancel':
        _cancel_local((str(message.get('scope')), str(message.get('id'))))
