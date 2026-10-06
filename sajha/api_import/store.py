"""
SAJHA MCP Server — API Import: import records.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

One JSON document per imported API at ``<api_import.records_dir>/<api_id>.json``
(default ``config/api_imports``), read and written through the storage backend (local
disk, S3, Azure Blob or GCS) like Studio's tool configs, so no database table is needed::

    {"api_id", "kind", "title", "version", "source": {"url", "uploaded"}, "server_url",
     "server_index", "server_variables", "auth": {<scheme>: {... secret references only}},
     "filters", "timeout_seconds", "rate_limit_per_minute",
     "operations": {"<op key>": {"tool_name", "fingerprint"}},
     "created_at", "updated_at", "updated_by"}
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sajha.api_import import settings
from sajha.api_import.naming import valid_prefix

logger = logging.getLogger(__name__)


def _storage():
    from sajha.core.storage import get_storage
    return get_storage()


def _path(api_id: str) -> str:
    if not valid_prefix(api_id):
        raise ValueError(f'invalid API id {api_id!r}')
    return f'{settings.records_dir()}/{api_id}.json'


def load(api_id: str) -> Optional[Dict[str, Any]]:
    try:
        path = _path(api_id)
        st = _storage()
        if not st.exists(path):
            return None
        data = st.read_json(path)
        return data if isinstance(data, dict) else None
    except ValueError:
        return None
    except Exception as e:
        logger.error(f'API import record {api_id} unreadable: {e}')
        return None


def save(record: Dict[str, Any]) -> None:
    _storage().write_json(_path(record['api_id']), record)


def delete(api_id: str) -> bool:
    try:
        return bool(_storage().delete(_path(api_id)))
    except FileNotFoundError:
        return False


def list_records() -> List[Dict[str, Any]]:
    out = []
    try:
        files = _storage().list_files(settings.records_dir(), '*.json')
    except Exception:
        files = []
    for rel in files:
        api_id = rel.rsplit('/', 1)[-1][:-len('.json')]
        rec = load(api_id)
        if rec:
            out.append(rec)
    return sorted(out, key=lambda r: r.get('api_id', ''))
