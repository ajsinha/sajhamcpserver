"""
SAJHA MCP Server — periodic snapshots of users, API keys and tools (``snapshots.*``).

Every ``snapshots.interval_minutes`` (default 10) one worker of the instance writes a signed,
chained JSON snapshot to ``snapshots.dir`` and keeps the last ``snapshots.keep`` (default 20),
so an auditor can see who and what existed at any point in the retained window and an
administrator can re-create users and persistent key records after losing the database. It
works with or without SAJHA Net (SAJHA Net §20.4 adds the net view once that exists).

* One writer: the worker holding the ``snapshots:writer`` lease (sajha/core/state/lease.py)
  writes; a per-interval claim in the state store keeps it to one snapshot per interval even
  when the lease moves. With ``state.backend: memory`` every worker is its own writer, so run
  one worker or use ``redis``/``database`` (docs/architecture/Scaling and State.md).
* Every write, rotation and failure is an audit event (``snapshot.written``,
  ``snapshot.rotated``, ``snapshot.failed``); a restore is ``snapshot.restored``.
* ``python -m sajha.snapshots`` lists, verifies, compares and restores from snapshots.

Owner guide: docs/architecture/Policy and Audit.md (Snapshots); format and checks: core.py.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from sajha.snapshots.core import SnapshotStore, collect_db, collect_tools, default_signer, instance_info

logger = logging.getLogger(__name__)

LEASE_KEY = 'snapshots:writer'
SLOT_PREFIX = 'snapshots:slot:'


def _cfg(key: str, default: str) -> str:
    from sajha.core.config import _get
    return _get(key, default)


def _bool(v: Any) -> bool:
    return str(v).strip().lower() in ('1', 'true', 'yes', 'on')


@dataclass
class SnapshotSettings:
    enabled: bool = True
    interval_minutes: float = 10.0
    keep: int = 20
    dir: str = 'data/snapshots'
    compress: bool = False

    @classmethod
    def from_config(cls) -> 'SnapshotSettings':
        def num(key, default, cast):
            try:
                return cast(_cfg(key, str(default)))
            except (TypeError, ValueError):
                logger.warning(f'snapshots: {key} is not a number; using {default}')
                return default
        return cls(enabled=_bool(_cfg('snapshots.enabled', 'true')),
                   interval_minutes=max(1.0, num('snapshots.interval_minutes', 10, float)),
                   keep=max(1, num('snapshots.keep', 20, int)),
                   dir=_cfg('snapshots.dir', 'data/snapshots') or 'data/snapshots',
                   compress=_bool(_cfg('snapshots.compress', 'false')))

    @property
    def interval_seconds(self) -> float:
        return self.interval_minutes * 60.0


def _audit(event: str, outcome: str, resource: Optional[str] = None, details: Any = None,
           actor: str = 'system') -> None:
    try:
        from sajha import audit
        audit.record(event, actor={'user': actor}, resource={'type': 'snapshot', 'id': resource} if resource else None,
                     outcome=outcome, details=details)
    except Exception as e:                       # audit never breaks the work it records
        logger.debug(f'snapshot audit: {e}')


class SnapshotService:
    """Collects, writes, rotates and audits snapshots; runs the periodic writer."""

    def __init__(self, settings: Optional[SnapshotSettings] = None, registry_getter: Optional[Callable] = None,
                 session_factory: Optional[Callable] = None, signer=None, state=None):
        self.settings = settings or SnapshotSettings.from_config()
        self.store = SnapshotStore(self.settings.dir, self.settings.keep, self.settings.compress)
        self._registry_getter = registry_getter
        self._session_factory = session_factory
        self._signer = signer
        self._state = state
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lease = None
        self.last_error = ''
        self.last_written: Optional[str] = None

    # pieces
    def signer(self):
        if self._signer is None:
            self._signer = default_signer()
        return self._signer

    def state(self):
        if self._state is None:
            from sajha.core.state import get_state_store
            self._state = get_state_store()
        return self._state

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from sajha.db.engine import get_db_session
        return get_db_session()

    def _registry(self):
        if self._registry_getter is not None:
            return self._registry_getter()
        try:
            from sajha.tools.tools_registry import get_tools_registry
            return get_tools_registry()
        except Exception as e:
            logger.debug(f'snapshots: no tools registry: {e}')
            return None

    def collect(self) -> Dict[str, Any]:
        db = self._session()
        try:
            content = collect_db(db)
        finally:
            db.close()
        content['tools'] = collect_tools(self._registry())
        content['instance'] = instance_info()
        return content

    # one snapshot
    def take(self, actor: str = 'system', reason: str = 'schedule') -> str:
        """Write one snapshot now, rotate, and audit both. Returns the file name."""
        try:
            name, env = self.store.write(self.collect(), self.signer())
        except Exception as e:
            self.last_error = str(e)
            _audit('snapshot.failed', 'error', details={'error': str(e)[:500], 'reason': reason}, actor=actor)
            raise
        body = env['snapshot']
        self.last_written, self.last_error = name, ''
        _audit('snapshot.written', 'success', name, actor=actor,
               details={'seq': body['seq'], 'sha256': env['sha256'], 'prev': (body.get('prev') or {}).get('sha256'),
                        'reason': reason, 'users': len(body['users']), 'api_keys': len(body['api_keys']),
                        'tools': len(body['tools']), 'dir': str(self.store.dir)})
        gone = self.store.rotate()
        if gone:
            _audit('snapshot.rotated', 'success', details={'deleted': gone, 'keep': self.store.keep}, actor=actor)
        return name

    # the periodic writer
    def _claim_slot(self, now: float) -> bool:
        slot = int(now // self.settings.interval_seconds)
        from sajha.core.state import WORKER_ID
        return bool(self.state().add(f'{SLOT_PREFIX}{slot}', WORKER_ID, ttl=self.settings.interval_seconds * 2))

    def _is_writer(self) -> bool:
        try:
            from sajha.core.state.lease import Lease
        except ImportError:                       # no lease primitive: the per-interval claim alone
            return True
        if self._lease is None:
            ttl = max(30.0, min(300.0, self.settings.interval_seconds))
            self._lease = Lease(LEASE_KEY, ttl=ttl, store=self.state())
        return self._lease.held or self._lease.try_acquire()

    def tick(self, now: Optional[float] = None) -> Optional[str]:
        """One scheduled attempt: write when this worker is the writer and the slot is free."""
        now = time.time() if now is None else now
        try:
            if not self._is_writer() or not self._claim_slot(now):
                return None
            return self.take()
        except Exception as e:
            logger.warning(f'snapshot not written: {e}')
            return None

    def _loop(self) -> None:
        iv = self.settings.interval_seconds
        while True:
            wait = iv - (time.time() % iv) + random.uniform(1.0, 5.0)    # every worker wakes in the same slot
            if self._stop.wait(wait):
                return
            self.tick()

    def start(self) -> bool:
        if not self.settings.enabled:
            return False
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name='sajha-snapshots', daemon=True)
            self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout)
        if self._lease is not None:
            try:
                self._lease.release()
            except Exception as e:
                logger.debug(f'snapshot lease release: {e}')

    def status(self) -> Dict[str, Any]:
        return {'enabled': self.settings.enabled, 'dir': str(self.store.dir), 'keep': self.store.keep,
                'interval_minutes': self.settings.interval_minutes, 'count': len(self.store.names()),
                'last_written': self.last_written, 'last_error': self.last_error,
                'writer': bool(self._lease is not None and self._lease.held)}


_service: Optional[SnapshotService] = None
_lock = threading.Lock()


def get_service() -> SnapshotService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = SnapshotService()
    return _service


def start_snapshots(registry=None) -> bool:
    """Start-up: the periodic writer (snapshots.enabled). The first snapshot is written one interval in."""
    global _service
    with _lock:
        _service = SnapshotService(registry_getter=(lambda: registry) if registry is not None else None)
    return _service.start()


def shutdown_snapshots() -> None:
    global _service
    s = _service
    if s is not None:
        s.stop()
    _service = None
