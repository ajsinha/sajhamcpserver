"""
SAJHA MCP Server — Storage Backend Abstraction
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Provides a unified interface for filesystem operations so the same codebase
runs identically on local Linux, Docker containers, and AWS (S3 + EFS).

Usage:
    from sajha.core.storage import get_storage
    storage = get_storage()  # returns LocalBackend or S3Backend based on config

    files = storage.list_files('config/tools', '*.json')
    content = storage.read_text('config/tools/fmp_company_profile.json')
    storage.write_text('config/tools/new_tool.json', json_str)
"""

import os
import io
import json
import time
import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)


# ── Abstract Base ────────────────────────────────────────────

class StorageBackend(ABC):
    """Abstract storage backend. All IO in SAJHA flows through this."""

    @abstractmethod
    def list_files(self, prefix: str, pattern: str = '*') -> List[str]:
        """List files matching pattern under prefix. Returns relative paths."""
        ...

    @abstractmethod
    def read_bytes(self, path: str) -> bytes:
        """Read file as bytes. Raises FileNotFoundError if missing."""
        ...

    @abstractmethod
    def read_text(self, path: str, encoding: str = 'utf-8') -> str:
        """Read file as text."""
        ...

    @abstractmethod
    def write_bytes(self, path: str, data: bytes) -> None:
        """Write bytes to path, creating parent dirs as needed."""
        ...

    @abstractmethod
    def write_text(self, path: str, content: str, encoding: str = 'utf-8') -> None:
        """Write text to path."""
        ...

    @abstractmethod
    def exists(self, path: str) -> bool:
        """Check if path exists."""
        ...

    @abstractmethod
    def delete(self, path: str) -> bool:
        """Delete file. Returns True if deleted, False if not found."""
        ...

    @abstractmethod
    def get_local_path(self, path: str) -> Path:
        """Get a local filesystem path for the file.
        For LocalBackend this is direct. For S3Backend this syncs to cache first.
        Critical for importlib.import_module() which needs actual .py files.
        """
        ...

    @abstractmethod
    def get_modified_time(self, path: str) -> float:
        """Get last modified timestamp (epoch seconds)."""
        ...

    def read_json(self, path: str) -> Dict[str, Any]:
        """Read and parse a JSON file."""
        return json.loads(self.read_text(path))

    def write_json(self, path: str, data: Dict[str, Any], indent: int = 2) -> None:
        """Write dict as formatted JSON."""
        self.write_text(path, json.dumps(data, indent=indent, ensure_ascii=False))


# ── Local Filesystem Backend ─────────────────────────────────

class LocalStorageBackend(StorageBackend):
    """Direct local filesystem. Default backend for development and on-prem."""

    def __init__(self, base_dir: str = '.'):
        self.base_dir = Path(base_dir).resolve()
        logger.info(f"LocalStorageBackend initialized: {self.base_dir}")

    def _resolve(self, path: str) -> Path:
        return self.base_dir / path

    def list_files(self, prefix: str, pattern: str = '*') -> List[str]:
        p = self._resolve(prefix)
        if not p.is_dir():
            return []
        return [str(f.relative_to(self.base_dir)) for f in sorted(p.glob(pattern)) if f.is_file()]

    def read_bytes(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    def read_text(self, path: str, encoding: str = 'utf-8') -> str:
        return self._resolve(path).read_text(encoding=encoding)

    def write_bytes(self, path: str, data: bytes) -> None:
        fp = self._resolve(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_bytes(data)

    def write_text(self, path: str, content: str, encoding: str = 'utf-8') -> None:
        fp = self._resolve(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding=encoding)

    def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    def delete(self, path: str) -> bool:
        fp = self._resolve(path)
        if fp.exists():
            fp.unlink()
            return True
        return False

    def get_local_path(self, path: str) -> Path:
        return self._resolve(path)

    def get_modified_time(self, path: str) -> float:
        return self._resolve(path).stat().st_mtime


# ── S3 Storage Backend ───────────────────────────────────────

class S3StorageBackend(StorageBackend):
    """
    AWS S3 backend with local cache for dynamic imports.

    Architecture:
    - Reads/writes go to S3 bucket
    - A local cache dir mirrors S3 for importlib (Python needs real .py files)
    - S3SyncManager periodically pulls changes (hot-reload equivalent)
    - Studio writes go to S3 first, then cache is updated

    Config (application.yml):
        storage:
          backend: s3
          s3:
            bucket: sajha-config-bucket
            prefix: v4.0.0/
            region: us-east-1
            cache_dir: /tmp/sajha-cache
            sync_interval: 60
    """

    def __init__(self, bucket: str, prefix: str = '', region: str = 'us-east-1',
                 cache_dir: str = '/tmp/sajha-cache'):
        try:
            import boto3
        except ImportError:
            raise ImportError("boto3 required for S3 backend: pip install boto3")

        self.bucket = bucket
        self.prefix = prefix.rstrip('/')
        self.region = region
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._s3 = boto3.client('s3', region_name=region)
        self._lock = threading.Lock()
        self._mod_cache: Dict[str, float] = {}

        logger.info(f"S3StorageBackend initialized: s3://{bucket}/{prefix} → {cache_dir}")

    def _s3_key(self, path: str) -> str:
        """Convert relative path to S3 key."""
        if self.prefix:
            return f"{self.prefix}/{path}"
        return path

    def _cache_path(self, path: str) -> Path:
        return self.cache_dir / path

    def list_files(self, prefix: str, pattern: str = '*') -> List[str]:
        import fnmatch
        s3_prefix = self._s3_key(prefix)
        if not s3_prefix.endswith('/'):
            s3_prefix += '/'

        results = []
        paginator = self._s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket, Prefix=s3_prefix):
            for obj in page.get('Contents', []):
                key = obj['Key']
                # Strip our prefix to get relative path
                if self.prefix:
                    rel_path = key[len(self.prefix) + 1:]
                else:
                    rel_path = key
                filename = Path(rel_path).name
                if fnmatch.fnmatch(filename, pattern):
                    results.append(rel_path)

        return sorted(results)

    def read_bytes(self, path: str) -> bytes:
        try:
            response = self._s3.get_object(Bucket=self.bucket, Key=self._s3_key(path))
            data = response['Body'].read()
            # Update cache
            self._write_cache(path, data)
            return data
        except self._s3.exceptions.NoSuchKey:
            raise FileNotFoundError(f"S3 object not found: s3://{self.bucket}/{self._s3_key(path)}")

    def read_text(self, path: str, encoding: str = 'utf-8') -> str:
        return self.read_bytes(path).decode(encoding)

    def write_bytes(self, path: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self.bucket, Key=self._s3_key(path), Body=data)
        self._write_cache(path, data)
        logger.debug(f"S3 write: s3://{self.bucket}/{self._s3_key(path)}")

    def write_text(self, path: str, content: str, encoding: str = 'utf-8') -> None:
        self.write_bytes(path, content.encode(encoding))

    def exists(self, path: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=self._s3_key(path))
            return True
        except Exception:
            return False

    def delete(self, path: str) -> bool:
        try:
            self._s3.delete_object(Bucket=self.bucket, Key=self._s3_key(path))
            cp = self._cache_path(path)
            if cp.exists():
                cp.unlink()
            return True
        except Exception:
            return False

    def get_local_path(self, path: str) -> Path:
        """Ensure file is in local cache and return path.
        This is critical for importlib.import_module() which needs real .py files.
        """
        cp = self._cache_path(path)
        if not cp.exists():
            data = self.read_bytes(path)  # this also writes cache
        return cp

    def get_modified_time(self, path: str) -> float:
        try:
            response = self._s3.head_object(Bucket=self.bucket, Key=self._s3_key(path))
            return response['LastModified'].timestamp()
        except Exception:
            return 0.0

    def _write_cache(self, path: str, data: bytes) -> None:
        """Write to local cache for importlib and hot-reload."""
        with self._lock:
            cp = self._cache_path(path)
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_bytes(data)

    def sync_prefix(self, prefix: str) -> int:
        """Pull all files under prefix from S3 to local cache.
        Returns count of files synced.
        """
        files = self.list_files(prefix)
        count = 0
        for f in files:
            try:
                self.read_bytes(f)  # reads from S3, writes to cache
                count += 1
            except Exception as e:
                logger.warning(f"Failed to sync {f}: {e}")
        logger.info(f"S3 sync: {count} files from {prefix}")
        return count


# ── S3 Sync Manager (Hot-Reload Equivalent) ──────────────────

class S3SyncManager:
    """
    Periodically syncs S3 → local cache and triggers reload callbacks.
    This is the AWS equivalent of the local HotReloadManager.

    On each sync cycle:
    1. List S3 objects under watched prefixes
    2. Compare LastModified with cached timestamps
    3. Download changed files to local cache
    4. Fire reload callbacks (same as local file watcher)
    """

    def __init__(self, storage: S3StorageBackend, interval: int = 60):
        self.storage = storage
        self.interval = interval
        self._callbacks: Dict[str, Callable] = {}
        self._timestamps: Dict[str, float] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def watch(self, prefix: str, callback: Callable) -> None:
        """Register a callback for changes under prefix."""
        self._callbacks[prefix] = callback
        logger.info(f"S3SyncManager watching: {prefix}")

    def start(self) -> None:
        """Start background sync thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._sync_loop, daemon=True, name='s3-sync')
        self._thread.start()
        logger.info(f"S3SyncManager started (interval={self.interval}s)")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _sync_loop(self) -> None:
        # Initial sync
        for prefix in self._callbacks:
            self.storage.sync_prefix(prefix)

        while not self._stop_event.is_set():
            self._stop_event.wait(self.interval)
            if self._stop_event.is_set():
                break
            for prefix, callback in self._callbacks.items():
                try:
                    changed = self._check_changes(prefix)
                    if changed:
                        logger.info(f"S3 changes detected in {prefix}: {len(changed)} files")
                        callback()
                except Exception as e:
                    logger.error(f"S3 sync error for {prefix}: {e}")

    def _check_changes(self, prefix: str) -> List[str]:
        """Check for new/modified files under prefix."""
        changed = []
        files = self.storage.list_files(prefix)
        for f in files:
            mtime = self.storage.get_modified_time(f)
            if f not in self._timestamps or mtime > self._timestamps[f]:
                self._timestamps[f] = mtime
                self.storage.read_bytes(f)  # sync to cache
                changed.append(f)
        return changed


# ── Factory ──────────────────────────────────────────────────

_storage: Optional[StorageBackend] = None


def init_storage(config: dict) -> StorageBackend:
    """Initialize storage backend from config dict.

    Config keys:
        storage.backend: 'local' | 's3'
        storage.base_dir: base directory for local backend (default '.')
        storage.s3.bucket: S3 bucket name
        storage.s3.prefix: S3 key prefix
        storage.s3.region: AWS region
        storage.s3.cache_dir: local cache directory
    """
    global _storage

    backend = config.get('storage.backend', os.environ.get('SAJHA_STORAGE_BACKEND', 'local'))

    if backend == 's3':
        _storage = S3StorageBackend(
            bucket=config.get('storage.s3.bucket', os.environ.get('SAJHA_S3_BUCKET', '')),
            prefix=config.get('storage.s3.prefix', os.environ.get('SAJHA_S3_PREFIX', '')),
            region=config.get('storage.s3.region', os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')),
            cache_dir=config.get('storage.s3.cache_dir', os.environ.get('SAJHA_S3_CACHE_DIR', '/tmp/sajha-cache')),
        )
    else:
        _storage = LocalStorageBackend(
            base_dir=config.get('storage.base_dir', os.environ.get('SAJHA_BASE_DIR', '.'))
        )

    return _storage


def get_storage() -> StorageBackend:
    """Get the initialized storage backend. Falls back to local if not initialized."""
    global _storage
    if _storage is None:
        _storage = LocalStorageBackend('.')
    return _storage
