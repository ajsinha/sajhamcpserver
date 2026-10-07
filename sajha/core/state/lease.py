"""
A renewing lease on the state store: one holder at a time across every worker and host.

:meth:`StateStore.lease_claim` / ``lease_renew`` / ``lease_release`` / ``lease_holder``
(sajha/core/state/base.py) are the primitives; :class:`Lease` keeps one held: it claims,
renews from a background thread every ``renew_every`` seconds (default a third of the TTL),
and reports loss (``held`` turns False and ``on_lost`` is called) when a renewal finds the
lease expired or taken, for example after a long pause. A holder that loses the lease must
stop the work it guards. A crashed holder stops renewing, so its lease expires after at
most ``ttl`` seconds and another worker can claim it.

The design is in docs/architecture/Scaling and State.md (Leases).

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class Lease:
    """Hold the lease at ``key`` as ``holder`` (default: this worker's id)."""

    def __init__(self, key: str, ttl: float = 30.0, holder: Optional[str] = None, store=None,
                 renew_every: Optional[float] = None, on_lost: Optional[Callable[['Lease'], None]] = None):
        if ttl <= 0:
            raise ValueError('a lease needs a positive ttl')
        from sajha.core import state as _state
        self.key = key
        self.ttl = float(ttl)
        self.holder = holder or _state.WORKER_ID
        self._store = store
        self.renew_every = float(renew_every) if renew_every else self.ttl / 3.0
        self.on_lost = on_lost
        self.held = False
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def store(self):
        if self._store is None:
            from sajha.core.state import get_state_store
            self._store = get_state_store()
        return self._store

    def try_acquire(self) -> bool:
        """Claim now (no waiting); on success the renewer starts. True when held."""
        with self._lock:
            if self.held:
                return True
            if not self.store.lease_claim(self.key, self.holder, self.ttl):
                return False
            self.held = True
            self._stop.clear()
            self._thread = threading.Thread(target=self._renew_loop, name=f'sajha-lease-{self.key}'[:60],
                                            daemon=True)
            self._thread.start()
            return True

    def renew(self) -> bool:
        """Renew once (the background thread does this); False and ``on_lost`` when lost."""
        ok = False
        try:
            ok = self.store.lease_renew(self.key, self.holder, self.ttl)
        except Exception as e:              # store unreachable: keep trying until the TTL runs out
            logger.warning(f'lease {self.key}: renewal failed: {e}')
            return self.held
        if not ok and self.held:
            self.held = False
            self._stop.set()
            logger.warning(f'lease {self.key}: lost (expired or taken by {self.store.lease_holder(self.key)})')
            if self.on_lost is not None:
                try:
                    self.on_lost(self)
                except Exception as e:
                    logger.debug(f'lease {self.key} on_lost: {e}')
        return ok

    def _renew_loop(self) -> None:
        while not self._stop.wait(self.renew_every):
            if not self.renew():
                return

    def release(self) -> bool:
        """Stop renewing and give the lease up; True when it was still ours."""
        with self._lock:
            self._stop.set()
            was = self.held
            self.held = False
            t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=max(1.0, self.renew_every))
        try:
            return self.store.lease_release(self.key, self.holder) and was
        except Exception as e:
            logger.debug(f'lease {self.key}: release: {e}')
            return False

    def current_holder(self) -> Optional[str]:
        return self.store.lease_holder(self.key)

    def __enter__(self) -> 'Lease':
        if not self.try_acquire():
            raise LeaseUnavailable(f'lease {self.key} is held by {self.current_holder()}')
        return self

    def __exit__(self, *exc) -> None:
        self.release()


class LeaseUnavailable(RuntimeError):
    """Someone else holds the lease."""
