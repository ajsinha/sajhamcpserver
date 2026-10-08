"""
SAJHA MCP Server — persistent API keys: hashed key records in a file.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Two files sit beside the database (owner decisions; docs/security/Security Model.md,
"Credential storage and files"):

* ``config/apikeys.json`` (``config.apikeys.path``) is the administrators' keys file. It is
  checked FIRST and wins over the database for every key it holds. A record holds the key's id,
  display prefix, name, the raw ``key`` (or, for older records, its ``sha256``), the owner's user
  ID, name and roles, the enabled flag, expiry, tool access, creation time and creator,
  revocation, and optionally ``test_admin`` (honoured only while
  ``sajhanet.test_admin_key.enabled``). Persistent database keys are also written here.
* ``config/apikeys_db.json`` (``auth.api_keys.db_dump_path``) is the database's keys, dumped
  every ``auth.api_keys.db_dump_interval_minutes`` (raw under plain credential storage, else the
  hash). It is the LAST fallback: used only when the database does not know a key or does not
  answer.

Lookup order: keys file -> database -> database dump.
* SAJHA rewrites the file atomically (a temporary file, then a rename) whenever a
  persistent key is created, changed, rotated or revoked, and re-reads it when it changes
  on disk (checked at most once a second when a lookup needs it, and by the hot-reload
  watch), so an operator may edit it, for example to revoke a key during an outage.
* The file is written with owner-only permissions (0600) and is git-ignored;
  ``config/apikeys.json.example`` documents the format.

The older format with a top-level ``apikeys`` list is never read: such a file is ignored
with a warning and replaced on the first write.

Owner guide: docs/security/Security Model.md ("Credential storage and files").
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


def reload_check_seconds() -> float:
    """``auth.credential_files.reload_check_seconds`` (default 300): how often a credential file is
    checked for hand edits. Lookups always use the copy in memory; writes through SAJHA's pages
    reload at once."""
    from sajha.core.config import _get
    try:
        return max(1.0, float(_get('auth.credential_files.reload_check_seconds', 300)))
    except (TypeError, ValueError):
        return 300.0


def record_hash(rec: Dict[str, Any]) -> str:
    """The SHA-256 a record is looked up by: of its raw ``key`` when it has one (the admin's
    file, plain storage), else its stored ``sha256``."""
    import hashlib
    raw = rec.get('key')
    if isinstance(raw, str) and raw:
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()
    return str(rec.get('sha256') or '').lower()


def test_admin_enabled() -> bool:
    """``sajhanet.test_admin_key.enabled``: records marked ``test_admin`` count only while on."""
    from sajha.core.config import _get
    v = _get('sajhanet.test_admin_key.enabled', True)
    return v if isinstance(v, bool) else str(v).strip().lower() in ('1', 'true', 'yes', 'on')


def test_admin_key() -> Optional[Dict[str, Any]]:
    """The usable ``test_admin`` record with a raw key in the administrators' keys file, while
    ``sajhanet.test_admin_key.enabled`` is on; else None."""
    if not test_admin_enabled():
        return None
    try:
        recs = get_persistent_keys().records()
    except Exception:
        return None
    return next((r for r in recs if r.get('test_admin') and r.get('key') and record_usable(r)), None)


def record_usable(rec: Dict[str, Any]) -> bool:
    """Enabled, not revoked, not expired."""
    if not rec.get('enabled', False) or rec.get('revoked_at'):
        return False
    if rec.get('test_admin') and not test_admin_enabled():
        return False
    exp = _parse(rec.get('expires_at'))
    return exp is None or exp > datetime.now(timezone.utc)


_store_lock = threading.Lock()


class PersistentKeyStore:
    """The records in one file, indexed by SHA-256; re-read when the file changes."""

    @property
    def CHECK_EVERY(self) -> float:      # noqa: N802 — seconds between change checks (hand edits)
        return reload_check_seconds()
    NOTE = ('SAJHA API keys file, maintained by administrators (Admin > API keys > Keys file). Keys here win '
            'over the database. Records hold the raw key ("key") or, for older records, its SHA-256 '
            '("sha256"). Keep this file private: git-ignored, owner-only. docs/security/Security Model.md')

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
                    records = [r for r in (data.get('keys') or [])
                               if isinstance(r, dict) and (r.get('key') or r.get('sha256'))]
                self._warn_permissions()
            self._records = records
            self._by_hash = {record_hash(r): r for r in records}
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
               'note': self.NOTE,
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
    rec = {
        'id': key.id,
        'prefix': key.key_prefix,
        'name': key.name,
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
    if getattr(key, 'key_value', None):
        rec['key'] = key.key_value
    else:
        rec['sha256'] = key.key_hash
    return rec


class DumpKeyStore(PersistentKeyStore):
    """``config/apikeys_db.json``: the database's keys, written every few minutes; read only when
    the database does not know a key or cannot be reached."""
    NOTE = ('SAJHA API keys dumped from the database every auth.api_keys.db_dump_interval_minutes. Written by '
            'the server; do not edit (edit config/apikeys.json instead). Used only when the database does not '
            'know a key or is unavailable.')


_dump: Optional[DumpKeyStore] = None


def dump_path() -> Path:
    from sajha.core.config import _get
    p = Path(str(_get('auth.api_keys.db_dump_path', 'config/apikeys_db.json') or 'config/apikeys_db.json'))
    return p if p.is_absolute() else Path.cwd() / p


def get_dump_keys() -> DumpKeyStore:
    global _dump
    with _store_lock:
        if _dump is None:
            _dump = DumpKeyStore(dump_path())
        return _dump


def set_dump_keys(store: Optional[DumpKeyStore]) -> None:
    global _dump
    with _store_lock:
        _dump = store


def write_dump(db) -> int:
    """Write every database key to the dump file (raw when stored plainly, else its hash)."""
    from sajha.db.models import ApiKey
    recs = [record_for(k, k.owner if k.owner_id else None) for k in db.query(ApiKey).all()]
    get_dump_keys()._write(recs)
    return len(recs)


_store: Optional[PersistentKeyStore] = None
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
