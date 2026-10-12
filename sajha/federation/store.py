"""
SAJHA MCP Server — federation store: admin-managed upstreams and approval state.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

One JSON document at ``federation.state_path``, read and written through the storage
backend (local disk, S3, Azure Blob or GCS), so every process that shares the backend
shares it::

    {"upstreams": [<upstream definition>, ...],          # added on /admin/federation
     "items": {"<upstream id>": {"tool:<name>": {"status": "approved", "hash": "...",
                                                 "flagged": false, "updated_at": "..."}}}}

Definitions hold secret *references* only.

Several workers (docs/architecture/Scaling and State.md §3): the document's revision is a counter in
the state store (``fed:store:<path>:rev``). A read reloads the document when the revision moved since
it was read, so an approval made on one worker is what every other worker reads next. A change runs
under a short state-store lease (``fed:store:<path>:lock``) and re-reads the document first, so a
worker never writes its stale copy over another worker's change; it then raises the revision and
announces it on the state-store channel ``fed:store`` (:meth:`subscribe`), so the federation managers
re-apply approvals without waiting for a restart.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


CHANNEL = 'fed:store'          # state-store channel: {"path", "rev", "origin", "upstreams"} after a change
LOCK_SECONDS = 10.0             # the change lease's TTL (a crashed holder blocks others at most this long)


class FederationStore:
    def __init__(self, path: str, storage=None, state=None):
        self.path = path
        self._storage = storage
        self._state = state
        self._lock = threading.RLock()
        self._data: Optional[Dict[str, Any]] = None
        self._rev: Optional[int] = None       # the revision self._data was read at
        self.origin = uuid.uuid4().hex        # tells this store's own announcements from other workers'

    def state(self):
        if self._state is None:
            from sajha.core.state import get_state_store
            return get_state_store()
        return self._state

    def _key(self, what: str) -> str:
        return f'fed:store:{self.path}:{what}'

    def revision(self) -> Optional[int]:
        """The shared revision of the document (None when the state store does not answer)."""
        try:
            return int(self.state().get(self._key('rev')) or 0)
        except Exception as e:
            logger.debug(f'federation store revision: {e}')
            return None

    @property
    def storage(self):
        if self._storage is None:
            from sajha.core.storage import get_storage
            self._storage = get_storage()
        return self._storage

    def _load(self) -> Dict[str, Any]:
        rev = self.revision()
        if self._data is not None and rev is not None and rev != self._rev:
            self._data = None                      # another worker changed it: read it again
        if self._data is None:
            data: Dict[str, Any] = {}
            try:
                if self.storage.exists(self.path):
                    data = self.storage.read_json(self.path) or {}
            except (ValueError, json.JSONDecodeError) as e:
                logger.error(f'federation store {self.path} is not valid JSON ({e}); starting empty, '
                             f'the file is left untouched until the next change')
            except Exception as e:
                logger.error(f'federation store {self.path} unreadable: {e}')
            data.setdefault('upstreams', [])
            data.setdefault('items', {})
            self._data = data
            self._rev = rev
        return self._data

    def _mutate(self, fn, upstreams=()) -> Any:
        """Apply ``fn(data) -> (result, changed)`` to a freshly read document under the change lease;
        save, raise the revision and announce it when it changed. Returns the result."""
        holder = f'{self.origin}:{threading.get_ident()}'
        rev = None
        with self._lock:
            locked = self._claim(holder)
            try:
                self._data = None                  # re-read before writing: never save a stale copy
                result, changed = fn(self._load())
                if changed:
                    self._save()
                    rev = self._bump()
            finally:
                if locked:
                    try:
                        self.state().lease_release(self._key('lock'), holder)
                    except Exception as e:
                        logger.debug(f'federation store lease release: {e}')
        if rev is not None:                        # outside the locks: subscribers read the store
            try:
                self.state().publish(CHANNEL, {'path': self.path, 'rev': rev, 'origin': self.origin,
                                               'upstreams': list(upstreams)})
            except Exception as e:
                logger.warning(f'federation store: announcing the change to other workers failed: {e}')
        return result

    def _claim(self, holder: str) -> bool:
        deadline = time.monotonic() + LOCK_SECONDS + 1
        while True:
            try:
                if self.state().lease_claim(self._key('lock'), holder, LOCK_SECONDS):
                    return True
            except Exception as e:                 # no state store: this process's lock only
                logger.debug(f'federation store lease: {e}')
                return False
            if time.monotonic() > deadline:
                logger.warning(f'federation store {self.path}: change lease still held elsewhere; going ahead')
                return False
            time.sleep(0.02)

    def _bump(self) -> Optional[int]:
        try:
            self._rev = int(self.state().incr(self._key('rev')))
            return self._rev
        except Exception as e:
            logger.debug(f'federation store revision bump: {e}')
            return None

    def subscribe(self, handler) -> Any:
        """Call ``handler(message)`` when another store instance (another worker) changed this document;
        returns the unsubscribe function (a no-op one when the state store has no pub/sub)."""
        def on(msg):
            if isinstance(msg, dict) and msg.get('path') == self.path and msg.get('origin') != self.origin:
                handler(msg)
        try:
            return self.state().subscribe(CHANNEL, on)
        except Exception as e:
            logger.debug(f'federation store subscribe: {e}')
            return lambda: None

    def _save(self) -> None:
        try:
            self.storage.write_json(self.path, self._data)
        except Exception as e:
            logger.error(f'federation store {self.path} could not be written: {e}')
            raise

    def reload(self) -> None:
        with self._lock:
            self._data = None
            self._load()

    # ── upstream definitions ───────────────────────────────────────
    def upstreams(self) -> List[Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._load()['upstreams'])

    def put_upstream(self, definition: Dict[str, Any]) -> None:
        def fn(data):
            ups = [u for u in data['upstreams'] if u.get('id') != definition.get('id')]
            ups.append(copy.deepcopy(definition))
            data['upstreams'] = sorted(ups, key=lambda u: str(u.get('id')))
            return None, True
        self._mutate(fn, [definition.get('id')])

    def delete_upstream(self, upstream_id: str) -> bool:
        def fn(data):
            before = len(data['upstreams'])
            data['upstreams'] = [u for u in data['upstreams'] if u.get('id') != upstream_id]
            data['items'].pop(upstream_id, None)
            gone = len(data['upstreams']) != before
            return gone, gone
        return self._mutate(fn, [upstream_id])

    # ── item approval state ────────────────────────────────────────
    def items(self, upstream_id: str) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._load()['items'].get(upstream_id, {}))

    def set_items(self, upstream_id: str, items: Dict[str, Dict[str, Any]]) -> None:
        """Replace one upstream's item records (written only when they changed)."""
        self.update_items(upstream_id, lambda records: items)

    def update_items(self, upstream_id: str, fn) -> Dict[str, Dict[str, Any]]:
        """Read-modify-write one upstream's records: ``fn(records)`` gets a copy of the current records
        (read again under the change lease) and returns the new ones, written only when they changed.
        Returns the records now stored."""
        def apply(data):
            current = data['items'].get(upstream_id) or {}
            new = fn(copy.deepcopy(current))
            if new == current:
                return copy.deepcopy(current), False
            data['items'][upstream_id] = copy.deepcopy(new)
            return copy.deepcopy(new), True
        return self._mutate(apply, [upstream_id])

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec='seconds')
