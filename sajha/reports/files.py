"""
SAJHA MCP Server — Reports file access: the storage backend, or the local disk for an absolute path.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``reports.dir`` and ``reports.output_dir`` are normally relative to the storage base and go
through the storage backend (local, S3, Azure Blob, GCS). An absolute path (``/srv/reports``) is
read and written with plain pathlib, as other subsystems treat absolute directories
(sajha/federation/config.py, sajha/auth/users_file.py): the local backend confines every path
to its base directory, so it cannot list one outside it.
"""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
from typing import Any, List


def _abs(path: str) -> bool:
    return os.path.isabs(str(path))


def _storage():
    from sajha.core.storage import get_storage
    return get_storage()


def list_files(prefix: str, pattern: str = '*') -> List[str]:
    """Files under ``prefix`` (recursive) whose name matches ``pattern``; absolute in, absolute out."""
    if not _abs(prefix):
        return _storage().list_files(prefix, pattern)
    base = Path(prefix)
    if not base.is_dir():
        return []
    return sorted(str(p).replace('\\', '/') for p in base.rglob('*')
                  if p.is_file() and fnmatch.fnmatch(p.name, pattern))


def read_text(path: str) -> str:
    return Path(path).read_text(encoding='utf-8') if _abs(path) else _storage().read_text(path)


def read_bytes(path: str) -> bytes:
    return Path(path).read_bytes() if _abs(path) else _storage().read_bytes(path)


def read_json(path: str) -> Any:
    return json.loads(read_text(path))


def exists(path: str) -> bool:
    return Path(path).exists() if _abs(path) else _storage().exists(path)


def modified_time(path: str) -> float:
    return Path(path).stat().st_mtime if _abs(path) else _storage().get_modified_time(path)


def write_text(path: str, text: str) -> None:
    if not _abs(path):
        _storage().write_text(path, text)
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')


def write_bytes(path: str, data: bytes) -> None:
    if not _abs(path):
        _storage().write_bytes(path, data)
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def write_json(path: str, data: Any) -> None:
    if not _abs(path):
        _storage().write_json_atomic(path, data)
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + '.tmp')
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding='utf-8')
    os.replace(tmp, p)


def delete(path: str) -> bool:
    if not _abs(path):
        return bool(_storage().delete(path))
    try:
        Path(path).unlink()
        return True
    except FileNotFoundError:
        return False


class _Backend:
    """The storage-backend methods the reports modules use, routed by :mod:`sajha.reports.files`."""
    list_files = staticmethod(list_files)
    read_text = staticmethod(read_text)
    read_bytes = staticmethod(read_bytes)
    read_json = staticmethod(read_json)
    exists = staticmethod(exists)
    get_modified_time = staticmethod(modified_time)
    write_text = staticmethod(write_text)
    write_bytes = staticmethod(write_bytes)
    write_json = staticmethod(write_json)
    write_json_atomic = staticmethod(write_json)
    delete = staticmethod(delete)


def backend() -> _Backend:
    return _Backend()
