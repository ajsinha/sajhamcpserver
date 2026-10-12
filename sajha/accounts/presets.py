"""
SAJHA MCP Server — connected accounts: provider presets installed at run time.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A provider pack (sajha/packs) brings a *preset*: the provider fields a service needs
(endpoints, scopes, ``api_hosts``) plus the client id and client-secret *reference* the
administrator gave when installing it. Presets are stored one JSON document per provider at
``config/accounts/provider_presets/<id>.json`` through the storage backend (local disk, S3,
Azure Blob or GCS), like API Import's records, so no database table is needed and every
worker on the same storage reads the same presets.

Field resolution with presets, per provider and field (sajha/accounts/providers.py):
``SAJHA_ACCOUNTS_PROVIDERS_<ID>_<FIELD>`` → ``accounts.providers.<id>.<field>`` (YAML) →
the preset → the built-in template. A preset never overrides what an operator configured.

The registry notices a changed preset on any worker: :func:`stamp` lists the preset files and
their modification times (cached for ``STAMP_TTL`` seconds per process), and the registry reloads
when the stamp differs from the one it was built with.

Design: docs/architecture/Connected Accounts.md §2 and §11
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

PRESETS_DIR = 'config/accounts/provider_presets'
#: Seconds a computed stamp is reused before the storage backend is listed again.
STAMP_TTL = 10.0
#: Fields an installer may never put in a preset (secrets are references only, and only the
#: administrator's install inputs carry the client id and secret reference).
FORBIDDEN_FIELDS = ('client_secret',)

_lock = threading.Lock()
_cached: Tuple[float, Optional[tuple]] = (0.0, None)


def _storage():
    from sajha.core.storage import get_storage
    return get_storage()


def _path(pid: str) -> str:
    from sajha.accounts.providers import PROVIDER_ID
    if not PROVIDER_ID.match(str(pid or '')):
        raise ValueError(f'invalid provider id {pid!r}')
    return f'{PRESETS_DIR}/{pid}.json'


def load(pid: str) -> Optional[Dict[str, Any]]:
    """The stored preset document ``{provider, fields, pack, installed_at, installed_by}``, or None."""
    try:
        path = _path(pid)
        st = _storage()
        if not st.exists(path):
            return None
        doc = st.read_json(path)
        return doc if isinstance(doc, dict) and isinstance(doc.get('fields'), dict) else None
    except ValueError:
        return None
    except Exception as e:
        logger.error(f'accounts: provider preset {pid} unreadable: {e}')
        return None


def load_all() -> Dict[str, Dict[str, Any]]:
    """Every stored preset's provider fields, by provider id (unreadable files are skipped)."""
    out: Dict[str, Dict[str, Any]] = {}
    try:
        files = _storage().list_files(PRESETS_DIR, '*.json')
    except Exception:
        files = []
    for rel in files:
        pid = rel.rsplit('/', 1)[-1][:-len('.json')]
        doc = load(pid)
        if doc:
            out[pid] = {k: v for k, v in doc['fields'].items() if k not in FORBIDDEN_FIELDS}
    return out


def save(pid: str, fields: Dict[str, Any], pack: str = '', user: str = '') -> None:
    bad = [k for k in fields if k in FORBIDDEN_FIELDS]
    if bad:
        raise ValueError(f'a provider preset may not carry {", ".join(bad)}; use client_secret_ref (env:NAME)')
    from datetime import datetime, timezone
    doc = {'provider': pid, 'fields': dict(fields), 'pack': pack,
           'installed_at': datetime.now(timezone.utc).isoformat(), 'installed_by': user}
    _storage().write_json(_path(pid), doc)
    invalidate()


def delete(pid: str) -> bool:
    try:
        ok = bool(_storage().delete(_path(pid)))
    except FileNotFoundError:
        ok = False
    invalidate()
    return ok


def merge(presets: Dict[str, Dict[str, Any]], configured: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Raw provider config: each preset with the operator's YAML fields laid over it."""
    out = {pid: dict(fields) for pid, fields in presets.items()}
    for pid, fields in configured.items():
        out[pid] = {**out.get(pid, {}), **dict(fields)}
    return out


def stamp() -> tuple:
    """(file, modified time) of every preset; cached for STAMP_TTL seconds in this process."""
    global _cached
    now = time.monotonic()
    with _lock:
        at, value = _cached
        if value is not None and now - at < STAMP_TTL:
            return value
    try:
        st = _storage()
        files = sorted(st.list_files(PRESETS_DIR, '*.json'))
        value = tuple((rel, st.get_modified_time(rel)) for rel in files)
    except Exception:
        value = ()
    with _lock:
        _cached = (now, value)
    return value


def invalidate() -> None:
    """Forget the cached stamp (after this process saved or deleted a preset)."""
    global _cached
    with _lock:
        _cached = (0.0, None)
