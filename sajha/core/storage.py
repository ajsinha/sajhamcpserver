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
        """List files recursively under prefix, matching `pattern` against the
        filename (fnmatch). Returns paths relative to the backend base. Consistent
        across local and S3 backends."""
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
        import fnmatch
        p = self._resolve(prefix)
        if not p.is_dir():
            return []
        # Recursive listing with the pattern matched against the *filename*, to match
        # S3StorageBackend semantics (object stores have no directories, so listing is
        # always recursive). For flat dirs this is identical to a top-level glob.
        return sorted(
            str(f.relative_to(self.base_dir))
            for f in p.rglob('*')
            if f.is_file() and fnmatch.fnmatch(f.name, pattern)
        )

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


# ── Object-store base (shared by S3 / Azure Blob / GCS) ──────

class _ObjectStorageBackend(StorageBackend):
    """
    Shared logic for cloud object stores (S3, Azure Blob, GCS).

    Object stores have no directories and no real file handles, so each concrete
    backend implements only six primitives (_fetch_bytes, _store_bytes,
    _object_exists, _delete_object, _list_keys, _object_mtime). This base layers the
    SAJHA contract on top: app-prefix namespacing, a local read-through cache (so
    importlib and other real-file consumers work), recursive listing with
    filename-pattern matching, JSON helpers, and prefix sync.
    """

    def __init__(self, prefix: str = '', cache_dir: str = '/tmp/sajha-cache'):
        self.prefix = prefix.strip('/')
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # key <-> logical-path mapping
    def _key(self, path: str) -> str:
        return f"{self.prefix}/{path}" if self.prefix else path

    def _rel(self, key: str) -> str:
        if self.prefix and key.startswith(self.prefix + '/'):
            return key[len(self.prefix) + 1:]
        return key

    def _cache_path(self, path: str) -> Path:
        return self.cache_dir / path

    def _write_cache(self, path: str, data: bytes) -> None:
        with self._lock:
            cp = self._cache_path(path)
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_bytes(data)

    # StorageBackend contract, expressed via the six primitives
    def list_files(self, prefix: str, pattern: str = '*') -> List[str]:
        import fnmatch
        kp = self._key(prefix).rstrip('/') + '/'
        out = []
        for key in self._list_keys(kp):
            rel = self._rel(key)
            if rel and fnmatch.fnmatch(Path(rel).name, pattern):
                out.append(rel)
        return sorted(out)

    def read_bytes(self, path: str) -> bytes:
        data = self._fetch_bytes(self._key(path))
        self._write_cache(path, data)
        return data

    def read_text(self, path: str, encoding: str = 'utf-8') -> str:
        return self.read_bytes(path).decode(encoding)

    def write_bytes(self, path: str, data: bytes) -> None:
        self._store_bytes(self._key(path), data)
        self._write_cache(path, data)

    def write_text(self, path: str, content: str, encoding: str = 'utf-8') -> None:
        self.write_bytes(path, content.encode(encoding))

    def exists(self, path: str) -> bool:
        return self._object_exists(self._key(path))

    def delete(self, path: str) -> bool:
        ok = self._delete_object(self._key(path))
        cp = self._cache_path(path)
        if cp.exists():
            cp.unlink()
        return ok

    def get_local_path(self, path: str) -> Path:
        """Materialize into the local cache and return the path (for importlib etc.)."""
        cp = self._cache_path(path)
        if not cp.exists():
            self.read_bytes(path)  # fetch + cache
        return cp

    def get_modified_time(self, path: str) -> float:
        return self._object_mtime(self._key(path))

    def sync_prefix(self, prefix: str) -> int:
        """Pull all objects under prefix into the local cache. Returns count synced."""
        count = 0
        for f in self.list_files(prefix):
            try:
                self.read_bytes(f)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to sync {f}: {e}", exc_info=True)
        logger.info(f"Object-store sync: {count} files from {prefix}")
        return count

    # primitives — each cloud backend implements these
    @abstractmethod
    def _fetch_bytes(self, key: str) -> bytes: ...
    @abstractmethod
    def _store_bytes(self, key: str, data: bytes) -> None: ...
    @abstractmethod
    def _object_exists(self, key: str) -> bool: ...
    @abstractmethod
    def _delete_object(self, key: str) -> bool: ...
    @abstractmethod
    def _list_keys(self, key_prefix: str) -> List[str]: ...
    @abstractmethod
    def _object_mtime(self, key: str) -> float: ...


# ── AWS S3 Backend ───────────────────────────────────────────

class S3StorageBackend(_ObjectStorageBackend):
    """
    AWS S3 backend (boto3). Credentials via the default boto3 chain — prefer an IAM
    role on EC2/ECS (no secrets in config). `endpoint_url` targets S3-compatible
    stores (MinIO, Cloudflare R2, Wasabi).
    """

    def __init__(self, bucket: str, prefix: str = '', region: str = 'us-east-1',
                 cache_dir: str = '/tmp/sajha-cache', endpoint_url: str = None):
        try:
            import boto3
        except ImportError:
            raise ImportError("boto3 required for S3 backend: pip install boto3")
        super().__init__(prefix=prefix, cache_dir=cache_dir)
        self.bucket = bucket
        self.region = region
        self._s3 = boto3.client('s3', region_name=region, endpoint_url=endpoint_url or None)
        logger.info(f"S3StorageBackend initialized: s3://{bucket}/{self.prefix} \u2192 {cache_dir}")

    def _fetch_bytes(self, key: str) -> bytes:
        try:
            return self._s3.get_object(Bucket=self.bucket, Key=key)['Body'].read()
        except self._s3.exceptions.NoSuchKey:
            raise FileNotFoundError(f"S3 object not found: s3://{self.bucket}/{key}")

    def _store_bytes(self, key: str, data: bytes) -> None:
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=data)

    def _object_exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False  # missing object is the common case — do not log

    def _delete_object(self, key: str) -> bool:
        try:
            self._s3.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            logger.warning(f"S3 delete error: {e}")
            return False

    def _list_keys(self, key_prefix: str) -> List[str]:
        keys = []
        paginator = self._s3.get_paginator('list_objects_v2')
        for page in paginator.paginate(Bucket=self.bucket, Prefix=key_prefix):
            for obj in page.get('Contents', []):
                keys.append(obj['Key'])
        return keys

    def _object_mtime(self, key: str) -> float:
        try:
            return self._s3.head_object(Bucket=self.bucket, Key=key)['LastModified'].timestamp()
        except Exception:
            return 0.0


# ── Azure Blob Storage Backend ───────────────────────────────

class AzureBlobStorageBackend(_ObjectStorageBackend):
    """
    Azure Blob Storage backend (azure-storage-blob).

    Auth precedence: a connection string (config/env), else account_url +
    DefaultAzureCredential (managed identity — no secrets in config).

    Config (application.yml):
        storage:
          backend: azure
          azure:
            container: sajha-config
            account_url: https://<acct>.blob.core.windows.net
            connection_string: ""        # optional alternative to account_url
            prefix: sajha/
            cache_dir: /tmp/sajha-cache
    """

    def __init__(self, container: str, account_url: str = '', connection_string: str = '',
                 prefix: str = '', cache_dir: str = '/tmp/sajha-cache'):
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError:
            raise ImportError("azure-storage-blob required for Azure backend: "
                              "pip install azure-storage-blob azure-identity")
        super().__init__(prefix=prefix, cache_dir=cache_dir)
        if connection_string:
            svc = BlobServiceClient.from_connection_string(connection_string)
        elif account_url:
            try:
                from azure.identity import DefaultAzureCredential
            except ImportError:
                raise ImportError("azure-identity required for account_url auth: pip install azure-identity")
            svc = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
        else:
            raise ValueError("Azure backend needs storage.azure.connection_string or storage.azure.account_url")
        self.container = container
        self._container = svc.get_container_client(container)
        logger.info(f"AzureBlobStorageBackend initialized: az://{container}/{self.prefix} \u2192 {cache_dir}")

    def _blob(self, key: str):
        return self._container.get_blob_client(key)

    def _fetch_bytes(self, key: str) -> bytes:
        from azure.core.exceptions import ResourceNotFoundError
        try:
            return self._blob(key).download_blob().readall()
        except ResourceNotFoundError:
            raise FileNotFoundError(f"Azure blob not found: {self.container}/{key}")

    def _store_bytes(self, key: str, data: bytes) -> None:
        self._blob(key).upload_blob(data, overwrite=True)

    def _object_exists(self, key: str) -> bool:
        try:
            return bool(self._blob(key).exists())
        except Exception:
            return False

    def _delete_object(self, key: str) -> bool:
        from azure.core.exceptions import ResourceNotFoundError
        try:
            self._blob(key).delete_blob()
            return True
        except ResourceNotFoundError:
            return False
        except Exception as e:
            logger.warning(f"Azure delete error: {e}")
            return False

    def _list_keys(self, key_prefix: str) -> List[str]:
        return [b.name for b in self._container.list_blobs(name_starts_with=key_prefix)]

    def _object_mtime(self, key: str) -> float:
        try:
            return self._blob(key).get_blob_properties().last_modified.timestamp()
        except Exception:
            return 0.0


# ── Google Cloud Storage Backend ─────────────────────────────

class GCSStorageBackend(_ObjectStorageBackend):
    """
    Google Cloud Storage backend (google-cloud-storage).

    Auth via Application Default Credentials — workload identity / attached service
    account (no keys in config).

    Config (application.yml):
        storage:
          backend: gcs
          gcs:
            bucket: sajha-config
            project: my-gcp-project
            prefix: sajha/
            cache_dir: /tmp/sajha-cache
    """

    def __init__(self, bucket: str, project: str = '', prefix: str = '',
                 cache_dir: str = '/tmp/sajha-cache'):
        try:
            from google.cloud import storage as gcs
        except ImportError:
            raise ImportError("google-cloud-storage required for GCS backend: pip install google-cloud-storage")
        super().__init__(prefix=prefix, cache_dir=cache_dir)
        self._client = gcs.Client(project=project) if project else gcs.Client()
        self.bucket = bucket
        self._bucket = self._client.bucket(bucket)
        logger.info(f"GCSStorageBackend initialized: gs://{bucket}/{self.prefix} \u2192 {cache_dir}")

    def _fetch_bytes(self, key: str) -> bytes:
        from google.cloud.exceptions import NotFound
        try:
            return self._bucket.blob(key).download_as_bytes()
        except NotFound:
            raise FileNotFoundError(f"GCS object not found: gs://{self.bucket}/{key}")

    def _store_bytes(self, key: str, data: bytes) -> None:
        self._bucket.blob(key).upload_from_string(data)

    def _object_exists(self, key: str) -> bool:
        try:
            return bool(self._bucket.blob(key).exists())
        except Exception:
            return False

    def _delete_object(self, key: str) -> bool:
        from google.cloud.exceptions import NotFound
        try:
            self._bucket.blob(key).delete()
            return True
        except NotFound:
            return False
        except Exception as e:
            logger.warning(f"GCS delete error: {e}")
            return False

    def _list_keys(self, key_prefix: str) -> List[str]:
        return [b.name for b in self._client.list_blobs(self.bucket, prefix=key_prefix)]

    def _object_mtime(self, key: str) -> float:
        try:
            blob = self._bucket.get_blob(key)
            return blob.updated.timestamp() if blob and blob.updated else 0.0
        except Exception:
            return 0.0


# ── S3 Sync Manager (Hot-Reload Equivalent) ──────────────────

class S3SyncManager:
    """
    Periodically syncs an object store → local cache and triggers reload callbacks.
    This is the cloud equivalent of the local HotReloadManager. Works with any
    object-store backend (S3, Azure Blob, GCS) since it only uses the shared
    _ObjectStorageBackend contract (list_files / read_bytes / get_modified_time).

    On each sync cycle:
    1. List objects under watched prefixes
    2. Compare modified time with cached timestamps
    3. Download changed files to local cache
    4. Fire reload callbacks (same as local file watcher)
    """

    def __init__(self, storage: '_ObjectStorageBackend', interval: int = 60):
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
                    logger.error(f"S3 sync error for {prefix}: {e}", exc_info=True)

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
    """Initialize the storage backend from config (default: local filesystem).

    Config keys:
        storage.backend: 'local' | 's3' | 'azure' | 'gcs'
        storage.base_dir: base directory for the local backend (default '.')
        storage.s3.{bucket,prefix,region,endpoint_url,cache_dir}
        storage.azure.{container,account_url,connection_string,prefix,cache_dir}
        storage.gcs.{bucket,project,prefix,cache_dir}

    Cloud SDKs (boto3 / azure-storage-blob / google-cloud-storage) are imported
    lazily inside each backend, so they are only required when that backend is
    actually selected — the default 'local' path needs none of them.
    """
    global _storage

    backend = config.get('storage.backend', os.environ.get('SAJHA_STORAGE_BACKEND', 'local'))

    if backend == 's3':
        _storage = S3StorageBackend(
            bucket=config.get('storage.s3.bucket', os.environ.get('SAJHA_S3_BUCKET', '')),
            prefix=config.get('storage.s3.prefix', os.environ.get('SAJHA_S3_PREFIX', '')),
            region=config.get('storage.s3.region', os.environ.get('AWS_DEFAULT_REGION', 'us-east-1')),
            cache_dir=config.get('storage.s3.cache_dir', os.environ.get('SAJHA_S3_CACHE_DIR', '/tmp/sajha-cache')),
            endpoint_url=config.get('storage.s3.endpoint_url', os.environ.get('SAJHA_S3_ENDPOINT_URL', '')) or None,
        )
    elif backend == 'azure':
        _storage = AzureBlobStorageBackend(
            container=config.get('storage.azure.container', os.environ.get('SAJHA_AZURE_CONTAINER', '')),
            account_url=config.get('storage.azure.account_url', os.environ.get('SAJHA_AZURE_ACCOUNT_URL', '')),
            connection_string=config.get('storage.azure.connection_string', os.environ.get('AZURE_STORAGE_CONNECTION_STRING', '')),
            prefix=config.get('storage.azure.prefix', os.environ.get('SAJHA_AZURE_PREFIX', '')),
            cache_dir=config.get('storage.azure.cache_dir', os.environ.get('SAJHA_AZURE_CACHE_DIR', '/tmp/sajha-cache')),
        )
    elif backend == 'gcs':
        _storage = GCSStorageBackend(
            bucket=config.get('storage.gcs.bucket', os.environ.get('SAJHA_GCS_BUCKET', '')),
            project=config.get('storage.gcs.project', os.environ.get('GOOGLE_CLOUD_PROJECT', '')),
            prefix=config.get('storage.gcs.prefix', os.environ.get('SAJHA_GCS_PREFIX', '')),
            cache_dir=config.get('storage.gcs.cache_dir', os.environ.get('SAJHA_GCS_CACHE_DIR', '/tmp/sajha-cache')),
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


def write_tool_config(local_path, config_or_text) -> str:
    """
    Persist a Studio/registry tool-config JSON through the active storage backend.

    `local_path` is the conventional local path (e.g. '.../config/tools/<name>.json');
    the object is stored at the storage-relative key 'config/tools/<name>.json', so the
    config lands in whatever backend is configured (local | s3 | azure | gcs). The tool's
    generated .py implementation is written separately to the local package by the
    generator, because importlib needs a real module on the Python path.
    """
    import os as _os
    rel = f"config/tools/{_os.path.basename(str(local_path))}"
    st = get_storage()
    if isinstance(config_or_text, (dict, list)):
        st.write_json(rel, config_or_text)
    else:
        st.write_text(rel, config_or_text)
    return rel
