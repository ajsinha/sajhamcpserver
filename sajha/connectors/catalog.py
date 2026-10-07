"""
SAJHA MCP Server — Data Connectors: the schema catalog cache.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Per process (caches stay per process, docs/architecture/Scaling and State.md): a connection's
allowed tables, and each described table, for ``connectors.catalog_ttl_seconds``. The key
includes the connection's fingerprint (an edit invalidates it) and, for per-user
connections, the caller (each user may see different tables). ``refresh`` re-reads.
The loaders are passed in by sajha/connectors/engine.py, which owns the database calls.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from sajha.connectors import settings
from sajha.connectors.model import Connection

_tables: Dict[Tuple[str, str, str], Tuple[float, List[Dict[str, Any]], bool]] = {}
_described: Dict[Tuple[str, str, str, str, str], Tuple[float, Dict[str, Any]]] = {}
_lock = threading.Lock()


def _user(conn: Connection) -> str:
    if not conn.per_user:
        return ''
    try:
        from sajha.observability.caller import current
        return current().user_id or 'anonymous'
    except Exception:
        return 'anonymous'


def _fresh(ts: float) -> bool:
    ttl = settings.catalog_ttl_seconds()
    return ttl > 0 and time.monotonic() - ts < ttl


def tables(conn: Connection, loader: Callable[[], List[Dict[str, Any]]], refresh: bool = False
           ) -> Tuple[List[Dict[str, Any]], bool]:
    """(allowed tables [{schema, name, type, comment}], truncated). ``loader`` lists every table."""
    key = (conn.id, conn.fingerprint() + repr(conn.allow_tables) + repr(conn.deny_tables), _user(conn))
    with _lock:
        hit = _tables.get(key)
    if hit and not refresh and _fresh(hit[0]):
        return hit[1], hit[2]
    allowed = [t for t in loader() if conn.table_allowed(t.get('schema') or '', t.get('name') or '')]
    cap = settings.catalog_max_tables()
    truncated = len(allowed) > cap
    allowed = allowed[:cap]
    with _lock:
        _tables[key] = (time.monotonic(), allowed, truncated)
        if refresh:
            for k in [k for k in _described if k[0] == conn.id and k[2] == key[2]]:
                _described.pop(k, None)
    return allowed, truncated


def described(conn: Connection, schema: str, table: str, loader: Callable[[], Dict[str, Any]],
              refresh: bool = False) -> Dict[str, Any]:
    key = (conn.id, conn.fingerprint(), _user(conn), schema, table)
    with _lock:
        hit = _described.get(key)
    if hit and not refresh and _fresh(hit[0]):
        return hit[1]
    detail = loader()
    with _lock:
        _described[key] = (time.monotonic(), detail)
    return detail


def invalidate(connection_id: Optional[str] = None) -> None:
    with _lock:
        for d in (_tables, _described):
            for k in [k for k in d if connection_id is None or k[0] == connection_id]:
                d.pop(k, None)


def resolve_in(conn: Connection, allowed: List[Dict[str, Any]], default_schema: str, catalogs: List[str],
               cat: str, schema: str, name: str) -> Optional[Tuple[str, str]]:
    """The allowed (schema, table) a reference [cat.][schema.]name means, or None."""
    if cat and cat.lower() not in catalogs:
        return None
    n = (name or '').lower()
    s = (schema or '').lower()
    cands = [t for t in allowed if (t.get('name') or '').lower() == n and
             (not s or (t.get('schema') or '').lower() == s)]
    if not cands:
        return None
    if len(cands) > 1:
        exact = [t for t in cands if t.get('name') == name and (not schema or t.get('schema') == schema)]
        if len(exact) == 1:
            cands = exact
    if len(cands) > 1 and not s:
        d = [t for t in cands if (t.get('schema') or '').lower() == (default_schema or '').lower()]
        cands = d
    if len(cands) != 1:
        return None
    return cands[0].get('schema') or '', cands[0]['name']
