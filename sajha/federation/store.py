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
"""

from __future__ import annotations

import copy
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FederationStore:
    def __init__(self, path: str, storage=None):
        self.path = path
        self._storage = storage
        self._lock = threading.RLock()
        self._data: Optional[Dict[str, Any]] = None

    @property
    def storage(self):
        if self._storage is None:
            from sajha.core.storage import get_storage
            self._storage = get_storage()
        return self._storage

    def _load(self) -> Dict[str, Any]:
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
        return self._data

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
        with self._lock:
            data = self._load()
            ups = [u for u in data['upstreams'] if u.get('id') != definition.get('id')]
            ups.append(copy.deepcopy(definition))
            data['upstreams'] = sorted(ups, key=lambda u: str(u.get('id')))
            self._save()

    def delete_upstream(self, upstream_id: str) -> bool:
        with self._lock:
            data = self._load()
            before = len(data['upstreams'])
            data['upstreams'] = [u for u in data['upstreams'] if u.get('id') != upstream_id]
            data['items'].pop(upstream_id, None)
            if len(data['upstreams']) != before:
                self._save()
                return True
            return False

    # ── item approval state ────────────────────────────────────────
    def items(self, upstream_id: str) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._load()['items'].get(upstream_id, {}))

    def set_items(self, upstream_id: str, items: Dict[str, Dict[str, Any]]) -> None:
        """Replace one upstream's item records (written only when they changed)."""
        with self._lock:
            data = self._load()
            if data['items'].get(upstream_id) == items:
                return
            data['items'][upstream_id] = copy.deepcopy(items)
            self._save()

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec='seconds')
