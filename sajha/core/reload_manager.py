"""
SAJHA MCP Server — Reload Manager Abstraction
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Unified interface for hot-reload across local filesystem and S3.
Selected automatically based on storage.backend config.

Usage:
    from sajha.core.reload_manager import init_reload_manager, get_reload_manager

    rm = init_reload_manager(config)          # LocalReloadManager or S3ReloadManager
    rm.watch('config/tools', on_tools_change) # register callback
    rm.start()                                # begin monitoring
"""

import os
import time
import logging
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set
from importlib import import_module, reload as reload_module

logger = logging.getLogger(__name__)


# ── Abstract Base ────────────────────────────────────────────

class ReloadManager(ABC):
    """
    Abstract hot-reload manager.
    Both local and S3 implementations fire the same callbacks
    when watched paths change, so ToolsRegistry, PromptsRegistry, etc.
    behave identically regardless of storage backend.
    """

    @abstractmethod
    def watch(self, prefix: str, callback: Callable, pattern: str = '*') -> None:
        """Register a callback for changes under prefix.
        callback signature: callback(action: str, name: str, path: str)
        action: 'created' | 'modified' | 'deleted'
        """
        ...

    @abstractmethod
    def watch_module(self, module_dir: str, callback: Callable) -> None:
        """Watch Python modules for changes (reimport on change).
        callback signature: callback(module_name: str)
        """
        ...

    @abstractmethod
    def start(self) -> None:
        """Start background monitoring thread."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop monitoring."""
        ...

    @abstractmethod
    def force_reload(self, prefix: str) -> int:
        """Force immediate check + reload for a prefix. Returns files changed."""
        ...

    @abstractmethod
    def get_stats(self) -> Dict:
        """Return monitoring statistics."""
        ...


# ── Local Filesystem Reload Manager ──────────────────────────

class LocalReloadManager(ReloadManager):
    """
    Watches local filesystem via polling (glob + mtime comparison).
    This is the default for development and on-prem deployments.
    Wraps the same logic as the original HotReloadManager.
    """

    def __init__(self, base_dir: str = '.', interval: int = 300):
        self.base_dir = Path(base_dir).resolve()
        self.interval = interval
        self._watches: Dict[str, dict] = {}      # prefix → {callback, pattern, timestamps}
        self._module_watches: Dict[str, dict] = {} # module_dir → {callback, timestamps}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._reload_count = 0
        logger.info(f"LocalReloadManager: base={self.base_dir}, interval={interval}s")

    def watch(self, prefix: str, callback: Callable, pattern: str = '*') -> None:
        self._watches[prefix] = {
            'callback': callback,
            'pattern': pattern,
            'timestamps': {},   # filename → mtime
            'known_files': set(),
        }
        # Initial scan
        self._scan_prefix(prefix)

    def watch_module(self, module_dir: str, callback: Callable) -> None:
        self._module_watches[module_dir] = {
            'callback': callback,
            'timestamps': {},
        }
        self._scan_modules(module_dir)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name='local-reload')
        self._thread.start()
        logger.info("LocalReloadManager started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("LocalReloadManager stopped")

    def force_reload(self, prefix: str) -> int:
        if prefix in self._watches:
            return self._check_prefix(prefix)
        return 0

    def get_stats(self) -> Dict:
        return {
            'backend': 'local',
            'base_dir': str(self.base_dir),
            'interval': self.interval,
            'watched_prefixes': list(self._watches.keys()),
            'watched_modules': list(self._module_watches.keys()),
            'total_reloads': self._reload_count,
        }

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            if self._stop.is_set():
                break
            for prefix in list(self._watches.keys()):
                try:
                    self._check_prefix(prefix)
                except Exception as e:
                    logger.error(f"Reload check error for {prefix}: {e}", exc_info=True)
            for module_dir in list(self._module_watches.keys()):
                try:
                    self._check_modules(module_dir)
                except Exception as e:
                    logger.error(f"Module check error for {module_dir}: {e}", exc_info=True)

    def _scan_prefix(self, prefix: str) -> None:
        w = self._watches[prefix]
        p = self.base_dir / prefix
        if not p.is_dir():
            return
        for f in p.glob(w['pattern']):
            if f.is_file():
                rel = str(f.relative_to(self.base_dir))
                w['timestamps'][rel] = f.stat().st_mtime
                w['known_files'].add(rel)

    def _scan_modules(self, module_dir: str) -> None:
        w = self._module_watches[module_dir]
        p = self.base_dir / module_dir
        if not p.is_dir():
            return
        for f in p.glob('*.py'):
            if f.is_file() and not f.name.startswith('__'):
                rel = str(f.relative_to(self.base_dir))
                w['timestamps'][rel] = f.stat().st_mtime

    def _check_prefix(self, prefix: str) -> int:
        w = self._watches[prefix]
        p = self.base_dir / prefix
        if not p.is_dir():
            return 0
        changed = 0
        current_files: Set[str] = set()
        for f in p.glob(w['pattern']):
            if not f.is_file():
                continue
            rel = str(f.relative_to(self.base_dir))
            current_files.add(rel)
            mtime = f.stat().st_mtime
            if rel not in w['timestamps']:
                w['timestamps'][rel] = mtime
                w['known_files'].add(rel)
                w['callback']('created', f.stem, rel)
                changed += 1
                self._reload_count += 1
            elif mtime > w['timestamps'][rel]:
                w['timestamps'][rel] = mtime
                w['callback']('modified', f.stem, rel)
                changed += 1
                self._reload_count += 1
        # Check for deletions
        deleted = w['known_files'] - current_files
        for rel in deleted:
            w['known_files'].discard(rel)
            w['timestamps'].pop(rel, None)
            w['callback']('deleted', Path(rel).stem, rel)
            changed += 1
            self._reload_count += 1
        return changed

    def _check_modules(self, module_dir: str) -> None:
        w = self._module_watches[module_dir]
        p = self.base_dir / module_dir
        if not p.is_dir():
            return
        for f in p.glob('*.py'):
            if f.name.startswith('__'):
                continue
            rel = str(f.relative_to(self.base_dir))
            mtime = f.stat().st_mtime
            if rel in w['timestamps'] and mtime > w['timestamps'][rel]:
                w['timestamps'][rel] = mtime
                module_name = f.stem
                w['callback'](module_name)
                self._reload_count += 1
            elif rel not in w['timestamps']:
                w['timestamps'][rel] = mtime


# ── S3 Reload Manager ────────────────────────────────────────

class S3ReloadManager(ReloadManager):
    """
    Polls S3 for changes and syncs to local cache.
    Drop-in replacement for LocalReloadManager on AWS.
    Uses the S3StorageBackend from storage.py for all IO.
    """

    def __init__(self, storage, interval: int = 60):
        """
        Args:
            storage: S3StorageBackend instance from sajha.core.storage
            interval: seconds between S3 polls
        """
        self.storage = storage
        self.interval = interval
        self._watches: Dict[str, dict] = {}
        self._module_watches: Dict[str, dict] = {}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._reload_count = 0
        logger.info(f"S3ReloadManager: bucket={storage.bucket}, interval={interval}s")

    def watch(self, prefix: str, callback: Callable, pattern: str = '*.json') -> None:
        self._watches[prefix] = {
            'callback': callback,
            'pattern': pattern,
            'timestamps': {},
        }
        # Initial sync
        self._initial_sync(prefix)

    def watch_module(self, module_dir: str, callback: Callable) -> None:
        self._module_watches[module_dir] = {
            'callback': callback,
            'timestamps': {},
        }
        self._initial_sync_modules(module_dir)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name='s3-reload')
        self._thread.start()
        logger.info("S3ReloadManager started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def force_reload(self, prefix: str) -> int:
        if prefix in self._watches:
            return self._check_prefix(prefix)
        return 0

    def get_stats(self) -> Dict:
        return {
            'backend': 's3',
            'bucket': self.storage.bucket,
            'prefix': self.storage.prefix,
            'interval': self.interval,
            'watched_prefixes': list(self._watches.keys()),
            'watched_modules': list(self._module_watches.keys()),
            'total_reloads': self._reload_count,
        }

    def _initial_sync(self, prefix: str) -> None:
        w = self._watches[prefix]
        files = self.storage.list_files(prefix, w['pattern'])
        for f in files:
            self.storage.get_local_path(f)  # sync to cache
            w['timestamps'][f] = self.storage.get_modified_time(f)
        logger.info(f"S3 initial sync: {len(files)} files from {prefix}")

    def _initial_sync_modules(self, module_dir: str) -> None:
        w = self._module_watches[module_dir]
        files = self.storage.list_files(module_dir, '*.py')
        for f in files:
            self.storage.get_local_path(f)
            w['timestamps'][f] = self.storage.get_modified_time(f)
        logger.info(f"S3 initial sync: {len(files)} modules from {module_dir}")

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(self.interval)
            if self._stop.is_set():
                break
            for prefix in list(self._watches.keys()):
                try:
                    self._check_prefix(prefix)
                except Exception as e:
                    logger.error(f"S3 reload check error for {prefix}: {e}", exc_info=True)
            for module_dir in list(self._module_watches.keys()):
                try:
                    self._check_modules(module_dir)
                except Exception as e:
                    logger.error(f"S3 module check error for {module_dir}: {e}", exc_info=True)

    def _check_prefix(self, prefix: str) -> int:
        w = self._watches[prefix]
        changed = 0
        current_files = set(self.storage.list_files(prefix, w['pattern']))

        for f in current_files:
            mtime = self.storage.get_modified_time(f)
            if f not in w['timestamps']:
                w['timestamps'][f] = mtime
                self.storage.get_local_path(f)
                w['callback']('created', Path(f).stem, f)
                changed += 1
                self._reload_count += 1
            elif mtime > w['timestamps'][f]:
                w['timestamps'][f] = mtime
                self.storage.get_local_path(f)
                w['callback']('modified', Path(f).stem, f)
                changed += 1
                self._reload_count += 1

        # Detect deletions
        old_files = set(w['timestamps'].keys())
        for f in old_files - current_files:
            del w['timestamps'][f]
            w['callback']('deleted', Path(f).stem, f)
            changed += 1
            self._reload_count += 1

        return changed

    def _check_modules(self, module_dir: str) -> None:
        w = self._module_watches[module_dir]
        files = self.storage.list_files(module_dir, '*.py')
        for f in files:
            mtime = self.storage.get_modified_time(f)
            if f in w['timestamps'] and mtime > w['timestamps'][f]:
                w['timestamps'][f] = mtime
                self.storage.get_local_path(f)
                w['callback'](Path(f).stem)
                self._reload_count += 1
            elif f not in w['timestamps']:
                w['timestamps'][f] = mtime
                self.storage.get_local_path(f)


# ── Factory ──────────────────────────────────────────────────

_reload_manager: Optional[ReloadManager] = None


def init_reload_manager(config: dict, storage=None) -> ReloadManager:
    """Initialize reload manager based on storage backend.

    Args:
        config: flattened config dict
        storage: StorageBackend instance (required for S3 mode)
    """
    global _reload_manager

    backend = config.get('storage.backend',
                         os.environ.get('SAJHA_STORAGE_BACKEND', 'local'))
    interval = int(config.get('hot_reload.interval_seconds',
                              os.environ.get('SAJHA_RELOAD_INTERVAL', '300')))

    if backend == 's3' and storage is not None:
        from sajha.core.storage import S3StorageBackend
        if isinstance(storage, S3StorageBackend):
            _reload_manager = S3ReloadManager(storage, interval=min(interval, 120))
        else:
            _reload_manager = LocalReloadManager(
                base_dir=config.get('storage.base_dir', '.'),
                interval=interval,
            )
    else:
        _reload_manager = LocalReloadManager(
            base_dir=config.get('storage.base_dir',
                                os.environ.get('SAJHA_BASE_DIR', '.')),
            interval=interval,
        )

    return _reload_manager


def get_reload_manager() -> Optional[ReloadManager]:
    return _reload_manager
