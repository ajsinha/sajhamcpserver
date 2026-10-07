"""
SAJHA MCP Server — persistent API keys: hashed key records in a file.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

API keys live in the database, which can be lost. Keys an administrator marks
*persistent* are also written, as records, to the file at ``config.apikeys.path``
(default ``config/apikeys.json``), so they keep working when the database does not
know them or cannot be reached:

* A record holds the key's id, display prefix, name, the SHA-256 of the key (never the
  key), the owner's user ID, name and roles (the users table may be gone too), the
  enabled flag, expiry, tool access, creation time and creator, and revocation.
* Verification checks the database first; only a key the database does not know (or a
  database that does not answer) is looked up here. When the database knows the key, the
  database decides, so disabling or revoking a key there always wins. When the database
  answers but the record's owner is not a user there (or is disabled), the key is refused.
* SAJHA rewrites the file atomically (a temporary file, then a rename) whenever a
  persistent key is created, changed, rotated or revoked, and re-reads it when it changes
  on disk (checked at most once a second when a lookup needs it, and by the hot-reload
  watch), so an operator may edit it, for example to revoke a key during an outage.
* The file is written with owner-only permissions (0600) and is git-ignored;
  ``config/apikeys.json.example`` documents the format.

The older plaintext format (a top-level ``apikeys`` list with raw ``key`` values) is
never read: such a file is ignored with a warning and replaced on the first write.

Owner guide: docs/security/Security Model.md ("Persistent API keys").
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

FORMAT = 'sajha-persistent-apikeys/1'


def _iso(d: Optional[datetime]) -> Optional[str]:
    if d is None:
        return None
    if d.tzinfo is not None:
        d = d.astimezone(timezone.utc).replace(tzinfo=None)
    return d.replace(microsecond=0).isoformat() + 'Z'


def _parse(s: Any) -> Optional[datetime]:
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def record_usable(rec: Dict[str, Any]) -> bool:
    """Enabled, not revoked, not expired."""
    if not rec.get('enabled', False) or rec.get('revoked_at'):
        return False
    exp = _parse(rec.get('expires_at'))
    return exp is None or exp > datetime.now(timezone.utc)


class PersistentKeyStore:
    """The records in one file, indexed by SHA-256; re-read when the file changes."""

    CHECK_EVERY = 1.0

    def __init__(self, path):
        self.config_path = Path(path)
        self._lock = threading.RLock()
        self._by_hash: Dict[str, Dict[str, Any]] = {}
        self._records: List[Dict[str, Any]] = []
        self._sig: Optional[tuple] = None
        self._checked = 0.0
        self._warned_legacy = False
        self.reload()

    # ── reading ──────────────────────────────────────────────────
    def _signature(self) -> Optional[tuple]:
        try:
            st = self.config_path.stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def reload(self) -> int:
        """Read the file now. Returns the number of records."""
        with self._lock:
            sig = self._signature()
            records: List[Dict[str, Any]] = []
            if sig is not None:
                try:
                    data = json.loads(self.config_path.read_text(encoding='utf-8') or '{}')
                except (OSError, ValueError) as e:
                    logger.error(f'persistent API keys: cannot read {self.config_path}: {e}; keeping the last good copy')
                    self._sig, self._checked = sig, time.time()
                    return len(self._records)
                if isinstance(data, dict) and 'apikeys' in data and 'keys' not in data:
                    if not self._warned_legacy:
                        logger.warning(f'persistent API keys: {self.config_path} is the old plaintext format; it is not '
                                       'read (no key in it works) and is replaced on the first persistent-key change. '
                                       'See config/apikeys.json.example.')
                        self._warned_legacy = True
                elif isinstance(data, dict):
                    records = [r for r in (data.get('keys') or []) if isinstance(r, dict) and r.get('sha256')]
                self._warn_permissions()
            self._records = records
            self._by_hash = {str(r['sha256']).lower(): r for r in records}
            self._sig, self._checked = sig, time.time()
            return len(records)

    def _warn_permissions(self) -> None:
        if os.name != 'posix':
            return
        try:
            mode = self.config_path.stat().st_mode & 0o777
        except OSError:
            return
        if mode & 0o077:
            logger.warning(f'persistent API keys: {self.config_path} is readable by others (mode {mode:o}); '
                           f'run chmod 600 on it')

    def _maybe_reload(self) -> None:
        now = time.time()
        if now - self._checked < self.CHECK_EVERY:
            return
        self._checked = now
        if self._signature() != self._sig:
            logger.info(f'persistent API keys: {self.config_path} changed on disk; reloading')
            self.reload()

    def lookup(self, key_hash: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._maybe_reload()
            rec = self._by_hash.get((key_hash or '').lower())
            return dict(rec) if rec is not None else None

    def records(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._maybe_reload()
            return [dict(r) for r in self._records]

    def ids(self) -> set:
        return {r.get('id') for r in self.records()}

    # ── writing ──────────────────────────────────────────────────
    def _write(self, records: List[Dict[str, Any]]) -> None:
        doc = {'format': FORMAT,
               'note': 'SAJHA persistent API keys: SHA-256 hashes only, never keys. Managed by the server '
                       '(Admin > API keys); edits are picked up automatically. docs/security/Security Model.md',
               'keys': records}
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix='.apikeys-', suffix='.json', dir=str(self.config_path.parent))
        try:
            if os.name == 'posix':
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(doc, f, indent=2, sort_keys=False)
                f.write('\n')
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.config_path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        self.reload()

    def upsert(self, record: Dict[str, Any]) -> None:
        """Add or replace the record with this ``id``."""
        with self._lock:
            self._maybe_reload()
            rest = [r for r in self._records if r.get('id') != record.get('id')]
            self._write(rest + [record])

    def remove(self, key_id: str) -> bool:
        with self._lock:
            self._maybe_reload()
            rest = [r for r in self._records if r.get('id') != key_id]
            if len(rest) == len(self._records):
                return False
            self._write(rest)
            return True


def record_for(key, owner=None) -> Dict[str, Any]:
    """The file record of an ``ApiKey`` row (owner: its ``User`` or None)."""
    try:
        tools = json.loads(key.tool_access_list or '[]')
    except ValueError:
        tools = []
    return {
        'id': key.id,
        'prefix': key.key_prefix,
        'name': key.name,
        'sha256': key.key_hash,
        'owner': owner.user_id if owner is not None else None,
        'owner_name': owner.user_name if owner is not None else None,
        'roles': list(owner.role_names) if owner is not None else ['api_consumer'],
        'enabled': bool(key.enabled) and key.revoked_at is None,
        'expires_at': _iso(key.expires_at),
        'tool_access_mode': key.tool_access_mode or 'all',
        'tool_access_list': tools if isinstance(tools, list) else [],
        'created_at': _iso(key.created_at),
        'created_by': key.created_by,
        'revoked_at': _iso(key.revoked_at),
        'revoked_by': key.revoked_by,
    }


_store: Optional[PersistentKeyStore] = None
_store_lock = threading.Lock()


def configured_path() -> Path:
    from sajha.core.config import get_settings
    p = Path(get_settings().config_apikeys_path or 'config/apikeys.json')
    return p if p.is_absolute() else Path.cwd() / p


def get_persistent_keys() -> PersistentKeyStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = PersistentKeyStore(configured_path())
        return _store


def set_persistent_keys(store: Optional[PersistentKeyStore]) -> None:
    """Tests and embedders: use this store (None: the configured file on next use)."""
    global _store
    with _store_lock:
        _store = store
