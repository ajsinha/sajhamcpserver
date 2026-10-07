"""
State store contract shared by every backend.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A :class:`StateStore` holds the small, hot, cross-request state that SAJHA used
to keep in one process's memory (OAuth codes, MCP sessions, task records,
rate-limit windows, LLM budgets) and carries pub/sub messages between workers
(change-bus events, task cancels, legacy-transport relays).

Values are JSON documents (``dict``/``list``/``str``/numbers/``None``).  Every
backend round-trips them through JSON, so code that works on the memory
backend works unchanged on Redis or the database.

Keys are plain strings without the configured prefix; the store adds it.
TTLs are seconds (``None`` = no expiry).
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

#: callback(message) for :meth:`StateStore.subscribe`; runs on a background thread.
MessageHandler = Callable[[Dict[str, Any]], None]


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def loads(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


class _NotHolder(Exception):
    """Aborts a lease update (``update`` writes nothing when ``fn`` raises)."""


def _holder_of(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        h = value.get("holder")
        return str(h) if h not in (None, "") else None
    if isinstance(value, str) and value:
        return value                      # a one-slot claim stores the worker id itself
    return None


class StateStore(ABC):
    """Key/value + counters + sliding windows + pub/sub, with TTLs."""

    #: backend name reported by /health: memory | redis | database
    backend: str = "abstract"
    #: True when other processes see this store (redis, database)
    shared: bool = False

    def __init__(self, prefix: str = "sajha:"):
        self.prefix = prefix or ""

    def k(self, key: str) -> str:
        return self.prefix + key

    # -- key/value ------------------------------------------------------

    @abstractmethod
    def get(self, key: str) -> Any:
        """The value, or None when missing/expired."""

    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store ``value`` (replaces; ``ttl`` None = keep forever)."""

    @abstractmethod
    def add(self, key: str, value: Any, ttl: Optional[float] = None) -> bool:
        """Store only if absent; True when stored."""

    @abstractmethod
    def pop(self, key: str) -> Any:
        """Atomically read and delete; None when missing."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete; True when something was deleted."""

    @abstractmethod
    def update(self, key: str, fn: Callable[[Any], Any], ttl: Optional[float] = None) -> Any:
        """
        Atomic read-modify-write.  ``fn(current_or_None)`` returns the new value
        (``None`` deletes the key).  ``ttl`` applies to the written value;
        ``None`` keeps the existing expiry.  An exception from ``fn`` aborts
        without writing and propagates.  Returns the new value.  ``fn`` may be
        called more than once (optimistic retries): keep it pure.
        """

    @abstractmethod
    def incr(self, key: str, amount: float = 1, ttl: Optional[float] = None) -> float:
        """Atomically add ``amount``; ``ttl`` is set when the key is created.  Returns the new value."""

    @abstractmethod
    def scan(self, prefix: str) -> Iterator[Tuple[str, Any]]:
        """(key without the store prefix, value) for every live key starting with ``prefix``."""

    def delete_prefix(self, prefix: str) -> int:
        n = 0
        for key, _ in list(self.scan(prefix)):
            n += bool(self.delete(key))
        return n

    def count(self, prefix: str) -> Optional[int]:
        """Number of keys under ``prefix`` when that is cheap to know, else None (no cap enforced)."""
        return None

    # -- leases (one holder at a time, renewed while held) ----------------
    #
    # A lease is a key whose value names its holder: ``{"holder", "claimed", "renewed", "ttl"}``.
    # Built on ``add`` (atomic add with TTL) and ``update`` (atomic read-modify-write), which
    # every backend implements atomically, so the semantics are the same on memory, redis and
    # database. The one-slot claims of workflow cron and quality probes (``add`` of the worker
    # id, never renewed) are unchanged; :meth:`lease_holder` reads those too.

    def lease_claim(self, key: str, holder: str, ttl: float) -> bool:
        """Take the lease for ``ttl`` seconds; True when ``holder`` now holds it (a holder that
        already holds it renews). False when someone else holds a live lease."""
        def fresh():
            now = time.time()
            return {"holder": holder, "claimed": now, "renewed": now, "ttl": float(ttl)}
        if self.add(key, fresh(), ttl=ttl):
            return True
        # held by us (renew), or it expired between the two calls (add again)
        return self.lease_renew(key, holder, ttl) or self.add(key, fresh(), ttl=ttl)

    def lease_renew(self, key: str, holder: str, ttl: Optional[float] = None) -> bool:
        """Extend the lease by ``ttl`` (default: its own) only while ``holder`` holds it; False
        when it expired or someone else holds it (the holder has lost it and must stop)."""
        if ttl is None:                   # the lease's own TTL (the write needs it up front)
            cur = self.get(key)
            ttl = float(cur.get("ttl") or 0) if isinstance(cur, dict) and _holder_of(cur) == holder else 0
        t = float(ttl)
        if t <= 0:
            return False

        def fn(cur):
            if not isinstance(cur, dict) or _holder_of(cur) != holder:
                raise _NotHolder()
            return dict(cur, renewed=time.time(), ttl=t)
        try:
            self.update(key, fn, ttl=t)
            return True
        except _NotHolder:
            return False

    def lease_release(self, key: str, holder: str) -> bool:
        """Give the lease up; True when ``holder`` held it (a lease held by another is untouched)."""
        def fn(cur):
            if _holder_of(cur) != holder:
                raise _NotHolder()
            return None
        try:
            self.update(key, fn)
            return True
        except _NotHolder:
            return False

    def lease_holder(self, key: str) -> Optional[str]:
        """Who holds the lease (or the one-slot claim) at ``key`` now; None when nobody."""
        return _holder_of(self.get(key))

    # -- sliding windows (rate limits, sign-in throttles) ----------------

    @abstractmethod
    def window_add(self, key: str, window: float, limit: Optional[int] = None) -> Tuple[bool, int]:
        """
        Record one hit in a ``window``-second sliding window, unless ``limit``
        hits are already in it.  Returns (recorded, hits in the window now).
        """

    @abstractmethod
    def window_count(self, key: str, window: float) -> int:
        """Hits in the last ``window`` seconds."""

    # -- pub/sub ----------------------------------------------------------

    @abstractmethod
    def publish(self, channel: str, message: Dict[str, Any]) -> None:
        """Deliver ``message`` to every subscriber of ``channel`` (all workers)."""

    @abstractmethod
    def subscribe(self, channel: str, handler: MessageHandler) -> Callable[[], None]:
        """Call ``handler(message)`` for each message on ``channel``; returns an unsubscribe function."""

    # -- lifecycle --------------------------------------------------------

    def ping(self) -> bool:
        return True

    def describe(self) -> Dict[str, Any]:
        return {"backend": self.backend, "shared": self.shared, "prefix": self.prefix}

    def close(self) -> None:
        pass
