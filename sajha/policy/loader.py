"""
SAJHA MCP Server — policy files: load through the storage backend, hot reload.

``policy.dir`` (default ``config/policies``) holds ``*.yaml``, ``*.yml`` and ``*.json``
files, read through the storage backend (local disk, S3, Azure Blob, GCS; an absolute path
is read from local disk), in name order.
The directory is rechecked at most every ``policy.reload_seconds`` (default 5), on the
next call, and reloaded when a file was added, removed or changed. A file that fails to
parse is reported and not enforced (``policy.on_error: ignore``, the default) or makes
every call fail closed (``deny``) until it is fixed.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import PurePosixPath
from typing import List, Optional, Tuple

from sajha.policy.model import Policy, PolicyParseError, parse_text

logger = logging.getLogger(__name__)

EXTENSIONS = ('.yaml', '.yml', '.json')


def policy_dir() -> str:
    from sajha.core.config import _get
    return (_get('policy.dir', 'config/policies') or 'config/policies').strip().rstrip('/')


def reload_seconds() -> float:
    from sajha.core.config import _get
    try:
        return max(0.0, float(_get('policy.reload_seconds', '5') or 5))
    except ValueError:
        return 5.0


def _storage(directory: str = ''):
    """The storage backend for ``directory``: an absolute path is read from local disk."""
    import os
    from sajha.core.storage import LocalStorageBackend, get_storage
    if directory and os.path.isabs(directory):
        return LocalStorageBackend(os.path.abspath(os.sep))
    return get_storage()


def _list(directory: str) -> List[str]:
    st = _storage(directory)
    try:
        files = st.list_files(directory, '*')
    except Exception as e:
        logger.debug(f'policy dir {directory}: {e}')
        return []
    return sorted(f for f in files if PurePosixPath(f).suffix.lower() in EXTENSIONS)


def _signature(directory: str, files: List[str]) -> Tuple:
    st = _storage(directory)
    sig = []
    for f in files:
        try:
            sig.append((f, st.get_modified_time(f)))
        except Exception:
            sig.append((f, None))
    return tuple(sig)


def load_dir(directory: Optional[str] = None) -> List[Policy]:
    """Every policy file in ``directory``; a broken file comes back with ``error`` set."""
    directory = directory or policy_dir()
    st = _storage(directory)
    out: List[Policy] = []
    for f in _list(directory):
        name = PurePosixPath(f).stem
        try:
            p = parse_text(st.read_text(f), name, f)
        except PolicyParseError as e:
            p = Policy(name=name, source=f, enabled=True, error=str(e))
            logger.error(f'Policy file {f} not enforced: {e}')
        except Exception as e:
            p = Policy(name=name, source=f, enabled=True, error=f'cannot read: {e}')
            logger.error(f'Policy file {f} not enforced: cannot read ({e})')
        out.append(p)
    names = [p.name for p in out]
    for p in out:
        if not p.error and names.count(p.name) > 1:
            p.error = f'policy name {p.name!r} is used by more than one file'
    return out


class PolicySet:
    """The loaded policies, refreshed lazily."""

    def __init__(self, directory: Optional[str] = None):
        self._directory = directory
        self._lock = threading.Lock()
        self._policies: List[Policy] = []
        self._sig: Optional[Tuple] = None
        self._checked = 0.0
        self.loaded_at = 0.0

    @property
    def directory(self) -> str:
        return self._directory or policy_dir()

    def policies(self) -> List[Policy]:
        now = time.monotonic()
        if self._sig is None or now - self._checked >= reload_seconds():
            self.refresh()
        return self._policies

    def refresh(self, force: bool = False) -> bool:
        """Reload when the files changed (or ``force``); True when reloaded."""
        with self._lock:
            self._checked = time.monotonic()
            files = _list(self.directory)
            sig = _signature(self.directory, files)
            if not force and sig == self._sig:
                return False
            self._policies = load_dir(self.directory)
            self._sig = sig
            self.loaded_at = time.time()
            n = sum(len(p.rules) for p in self._policies if p.enabled and not p.error)
            logger.info(f'Policies: {len(self._policies)} file(s) from {self.directory}, {n} enforced rule(s)')
            return True

    def set_policies(self, policies: List[Policy]) -> None:
        """Use these policies instead of the directory (tests, embedding)."""
        with self._lock:
            self._policies = list(policies)
            self._sig = ('fixed',)
            self._checked = float('inf')
            self.loaded_at = time.time()
