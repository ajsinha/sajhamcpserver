"""
In-process state store (the default: one process, nothing shared).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Values are kept JSON-encoded so the memory backend behaves like the shared
ones (a caller never mutates a stored value by accident).  Expiry is lazy on
access plus a sweep every few thousand writes.  Pub/sub is a direct call to
the handlers in this process.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from sajha.core.state.base import MessageHandler, StateStore, dumps, loads

logger = logging.getLogger(__name__)

_SWEEP_EVERY = 2000


class MemoryStateStore(StateStore):
    backend = "memory"
    shared = False

    def __init__(self, prefix: str = "sajha:"):
        super().__init__(prefix)
        self._lock = threading.RLock()
        self._data: Dict[str, Tuple[str, Optional[float]]] = {}     # key -> (json, expires_at)
        self._windows: Dict[str, List[float]] = {}
        self._subs: Dict[str, List[MessageHandler]] = {}
        self._writes = 0

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _exp(ttl: Optional[float]) -> Optional[float]:
        return time.time() + ttl if ttl is not None else None

    def _live(self, key: str) -> Optional[Tuple[str, Optional[float]]]:
        item = self._data.get(key)
        if item is not None and item[1] is not None and item[1] <= time.time():
            self._data.pop(key, None)
            return None
        return item

    def _wrote(self) -> None:
        self._writes += 1
        if self._writes % _SWEEP_EVERY == 0:
            now = time.time()
            for k in [k for k, (_, e) in self._data.items() if e is not None and e <= now]:
                self._data.pop(k, None)

    # -- key/value -----------------------------------------------------------

    def get(self, key: str) -> Any:
        with self._lock:
            item = self._live(key)
        return loads(item[0]) if item else None

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        raw = dumps(value)
        with self._lock:
            self._data[key] = (raw, self._exp(ttl))
            self._wrote()

    def add(self, key: str, value: Any, ttl: Optional[float] = None) -> bool:
        raw = dumps(value)
        with self._lock:
            if self._live(key) is not None:
                return False
            self._data[key] = (raw, self._exp(ttl))
            self._wrote()
            return True

    def pop(self, key: str) -> Any:
        with self._lock:
            item = self._live(key)
            self._data.pop(key, None)
        return loads(item[0]) if item else None

    def delete(self, key: str) -> bool:
        with self._lock:
            existed = self._live(key) is not None
            self._data.pop(key, None)
            self._windows.pop(key, None)
            return existed

    def update(self, key: str, fn: Callable[[Any], Any], ttl: Optional[float] = None) -> Any:
        with self._lock:
            item = self._live(key)
            new = fn(loads(item[0]) if item else None)
            if new is None:
                self._data.pop(key, None)
                return None
            expires = self._exp(ttl) if ttl is not None else (item[1] if item else None)
            self._data[key] = (dumps(new), expires)
            self._wrote()
            return loads(self._data[key][0])

    def incr(self, key: str, amount: float = 1, ttl: Optional[float] = None) -> float:
        with self._lock:
            item = self._live(key)
            if item is None:
                value, expires = amount, self._exp(ttl)
            else:
                value, expires = loads(item[0]) + amount, item[1]
            self._data[key] = (dumps(value), expires)
            self._wrote()
            return value

    def scan(self, prefix: str) -> Iterator[Tuple[str, Any]]:
        with self._lock:
            items = [(k, v) for k, v in self._data.items() if k.startswith(prefix)]
        now = time.time()
        for k, (raw, exp) in items:
            if exp is None or exp > now:
                yield k, loads(raw)

    def delete_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [k for k in self._data if k.startswith(prefix)]
            wkeys = [k for k in self._windows if k.startswith(prefix)]
            for k in keys:
                self._data.pop(k, None)
            for k in wkeys:
                self._windows.pop(k, None)
            return len(keys) + len(wkeys)

    def count(self, prefix: str) -> Optional[int]:
        now = time.time()
        with self._lock:
            return sum(1 for k, (_, e) in self._data.items() if k.startswith(prefix) and (e is None or e > now))

    # -- windows -------------------------------------------------------------

    def window_add(self, key: str, window: float, limit: Optional[int] = None) -> Tuple[bool, int]:
        now = time.time()
        with self._lock:
            hits = [t for t in self._windows.get(key, ()) if t > now - window]
            if limit is not None and len(hits) >= limit:
                self._windows[key] = hits
                return False, len(hits)
            hits.append(now)
            self._windows[key] = hits
            return True, len(hits)

    def window_count(self, key: str, window: float) -> int:
        now = time.time()
        with self._lock:
            hits = [t for t in self._windows.get(key, ()) if t > now - window]
            if hits:
                self._windows[key] = hits
            else:
                self._windows.pop(key, None)
            return len(hits)

    # -- pub/sub -------------------------------------------------------------

    def publish(self, channel: str, message: Dict[str, Any]) -> None:
        with self._lock:
            handlers = list(self._subs.get(channel, ()))
        payload = loads(dumps(message))
        for h in handlers:
            try:
                h(payload)
            except Exception as e:     # a broken handler must not break the publisher
                logger.warning(f"state handler on {channel} failed: {e}")

    def subscribe(self, channel: str, handler: MessageHandler) -> Callable[[], None]:
        with self._lock:
            self._subs.setdefault(channel, []).append(handler)

        def unsubscribe() -> None:
            with self._lock:
                lst = self._subs.get(channel, [])
                if handler in lst:
                    lst.remove(handler)
        return unsubscribe
