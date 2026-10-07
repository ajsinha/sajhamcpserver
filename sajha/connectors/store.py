"""
SAJHA MCP Server — Data Connectors: connection records.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

One JSON document per connection at ``<connectors.records_dir>/<id>.json`` (default
``config/connectors``), read and written through the storage backend (local disk, S3, Azure
Blob or GCS), so no database table is needed. :func:`get` keeps a parsed copy per process and
re-reads the document when its modification time changes (checked at most every
``connectors.record_refresh_seconds``), so an edit made on one worker reaches the others.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from sajha.connectors import settings
from sajha.connectors.model import Connection, ConnectorConfigError, parse

logger = logging.getLogger(__name__)

_ID = re.compile(r'^[a-z][a-z0-9_]{0,39}$')
_cache: Dict[str, Tuple[float, float, Optional[Connection], str]] = {}   # id -> (checked, mtime, conn, error)
_lock = threading.Lock()


def _storage():
    from sajha.core.storage import get_storage
    return get_storage()


def path(cid: str) -> str:
    if not isinstance(cid, str) or not _ID.match(cid):
        raise ValueError(f'invalid connection id {cid!r}')
    return f'{settings.records_dir()}/{cid}.json'


def load_raw(cid: str) -> Optional[Dict[str, Any]]:
    try:
        p = path(cid)
        st = _storage()
        if not st.exists(p):
            return None
        data = st.read_json(p)
        return data if isinstance(data, dict) else None
    except ValueError:
        return None
    except Exception as e:
        logger.error(f'connection record {cid} unreadable: {e}')
        return None


def save(record: Dict[str, Any]) -> None:
    _storage().write_json(path(record['id']), record)
    forget(record['id'])


def delete(cid: str) -> bool:
    forget(cid)
    try:
        return bool(_storage().delete(path(cid)))
    except (FileNotFoundError, ValueError):
        return False


def forget(cid: Optional[str] = None) -> None:
    with _lock:
        if cid is None:
            _cache.clear()
        else:
            _cache.pop(cid, None)


def ids() -> List[str]:
    try:
        files = _storage().list_files(settings.records_dir(), '*.json')
    except Exception:
        files = []
    out = []
    for rel in files:
        cid = rel.rsplit('/', 1)[-1][:-len('.json')]
        if _ID.match(cid):
            out.append(cid)
    return sorted(set(out))


def get(cid: str) -> Tuple[Optional[Connection], str]:
    """(connection, '') or (None, why). Cached per process; re-read when the record changes."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(cid)
    if hit and now - hit[0] < settings.record_refresh_seconds():
        return hit[2], hit[3]
    try:
        p = path(cid)
    except ValueError as e:
        return None, str(e)
    st = _storage()
    try:
        mtime = st.get_modified_time(p) if st.exists(p) else -1.0
    except Exception:
        mtime = -2.0
    if hit and hit[1] == mtime and mtime >= 0:
        with _lock:
            _cache[cid] = (now, mtime, hit[2], hit[3])
        return hit[2], hit[3]
    conn, err = None, ''
    raw = load_raw(cid) if mtime >= 0 else None
    if raw is None:
        err = f'connection {cid!r} does not exist'
    else:
        try:
            conn = parse(raw)
        except ConnectorConfigError as e:
            err = f'connection {cid!r} is not valid: {e}'
    with _lock:
        _cache[cid] = (now, mtime, conn, err)
    return conn, err


def all_records() -> List[Dict[str, Any]]:
    return [r for r in (load_raw(c) for c in ids()) if r]
