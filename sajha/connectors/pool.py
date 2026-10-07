"""
SAJHA MCP Server — Data Connectors: idle-connection pool.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Per process, keyed by (connection id, connection fingerprint): an edit that changes how a
connection opens starts a new key and the old idle connections are closed. At most
``connectors.pool_size`` idle connections per key, each recycled after
``connectors.pool_max_age_seconds``. A connection that timed out, failed or was cancelled is
closed, never returned. Per-user (connected-account) connections never come here.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional, Tuple

from sajha.connectors import settings

_idle: Dict[Tuple[str, str], Deque[Tuple[Any, float, Callable[[Any], None]]]] = {}
_lock = threading.Lock()


def take(key: Tuple[str, str]) -> Optional[Any]:
    now = time.monotonic()
    stale = []
    got = None
    with _lock:
        q = _idle.get(key)
        while q:
            dbc, born, closer = q.popleft()
            if now - born > settings.pool_max_age_seconds():
                stale.append((dbc, closer))
                continue
            got = (dbc, born)
            break
    for dbc, closer in stale:
        closer(dbc)
    if got is None:
        return None
    _born[id(got[0])] = got[1]
    return got[0]


_born: Dict[int, float] = {}


def give(key: Tuple[str, str], dbc: Any, closer: Callable[[Any], None]) -> None:
    born = _born.pop(id(dbc), time.monotonic())
    with _lock:
        # drop idle connections of an older definition of the same connection
        for k in [k for k in _idle if k[0] == key[0] and k != key]:
            for old, _b, c in _idle.pop(k):
                _close_later(old, c)
        q = _idle.setdefault(key, deque())
        if len(q) < settings.pool_size() and time.monotonic() - born <= settings.pool_max_age_seconds():
            q.append((dbc, born, closer))
            return
    closer(dbc)


def created(dbc: Any) -> None:
    _born[id(dbc)] = time.monotonic()


def discard(dbc: Any, closer: Callable[[Any], None]) -> None:
    _born.pop(id(dbc), None)
    closer(dbc)


def _close_later(dbc, closer) -> None:
    threading.Thread(target=closer, args=(dbc,), daemon=True).start()


def clear(connection_id: Optional[str] = None) -> int:
    """Close idle connections (of one connection, or all); returns how many."""
    with _lock:
        keys = [k for k in _idle if connection_id is None or k[0] == connection_id]
        items = [it for k in keys for it in _idle.pop(k)]
    for dbc, _b, closer in items:
        closer(dbc)
    return len(items)


def stats() -> Dict[str, int]:
    with _lock:
        out: Dict[str, int] = {}
        for (cid, _fp), q in _idle.items():
            out[cid] = out.get(cid, 0) + len(q)
        return out
