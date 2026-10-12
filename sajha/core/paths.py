"""
SAJHA MCP Server — the temporary folder
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Everything SAJHA writes temporarily goes under one folder, ``app.tmp_dir`` (env
``SAJHA_APP_TMP_DIR``). Unset or empty, it is the system temp directory (``TMPDIR``, else
``/tmp`` on Linux), the way ``tempfile.gettempdir()`` finds it.

* ``apply_tmp_dir()`` runs at start-up (the server and the ``python -m sajha.*`` commands):
  creates the folder if missing (mode 0700), refuses an unusable one with ``TmpDirError``,
  sets ``tempfile.tempdir`` (every ``tempfile`` call in the process, SAJHA's and libraries',
  uses it) and ``TMPDIR``/``TEMP``/``TMP`` in ``os.environ`` (so child processes inherit it).
* ``tmp_dir()`` is the folder; ``child_tmp_env()`` the three variables for a child process
  started with an explicit environment.
* SAJHA's own temporary entries are named ``sajha-<kind>-p<pid>-...`` (``tmp_prefix``);
  ``register_tmp`` removes one on normal exit, and ``sweep_tmp`` (at server start-up) removes
  ``sajha-*`` entries older than ``app.tmp_max_age_hours`` whose process is gone. Nothing
  else in the folder is ever touched.
* ``duckdb_connect`` opens DuckDB with its spill directory under the folder.

docs/getting-started/Configuration Reference.md (the keys); docs/getting-started/Storage Guide.md
("Temporary files").
"""

from __future__ import annotations

import atexit
import itertools
import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

KEY = 'app.tmp_dir'
ENV = 'SAJHA_APP_TMP_DIR'
MAX_AGE_KEY = 'app.tmp_max_age_hours'
DEFAULT_MAX_AGE_HOURS = 24.0

#: SAJHA's temporary entries all start with this; the sweep looks at nothing else
PREFIX = 'sajha-'
#: ``sajha-*`` names that are not leftovers (the object-storage read-through cache)
KEEP = frozenset({'sajha-cache'})
_PID = re.compile(r'^sajha-[a-z0-9_-]*?-p(\d+)-')

#: the system temp directory as the process found it, before SAJHA changed anything
_SYSTEM_TMP = tempfile.gettempdir()

_lock = threading.Lock()
_applied: Optional[str] = None
_registered: set = set()
_checked: set = set()
_counter = itertools.count(1)


class TmpDirError(ValueError):
    """``app.tmp_dir`` names something SAJHA cannot use."""


def configured_tmp_dir() -> str:
    """The folder ``app.tmp_dir`` names (absolute), or the system temp directory when unset or empty."""
    from sajha.core.config import _get
    raw = str(_get(KEY, '') or '').strip()
    return os.path.abspath(os.path.expanduser(raw)) if raw else _SYSTEM_TMP


def validate_tmp_dir(path: str) -> str:
    """``path`` as a usable temp folder: created (mode 0700) when missing; raises TmpDirError when it
    is not a directory or not writable."""
    path = os.path.abspath(os.path.expanduser(str(path)))
    where = f'{KEY} ({ENV}) = {path!r}'
    if not os.path.exists(path):
        try:
            os.makedirs(path, mode=0o700)
            os.chmod(path, 0o700)
        except FileExistsError:
            pass
        except OSError as e:
            raise TmpDirError(f'{where}: cannot create the folder: {e.strerror or e}') from None
    if not os.path.isdir(path):
        raise TmpDirError(f'{where} is not a directory')
    try:
        fd, probe = tempfile.mkstemp(prefix=PREFIX + 'probe-', dir=path)
        os.close(fd)
        os.unlink(probe)
    except OSError as e:
        raise TmpDirError(f'{where} is not writable: {e.strerror or e}') from None
    return path


def tmp_dir() -> str:
    """SAJHA's temporary folder: the one applied at start-up, else the configured one (validated
    once per path, and again if it disappears)."""
    if _applied:
        return _applied
    path = configured_tmp_dir()
    if path in _checked and os.path.isdir(path):
        return path
    path = validate_tmp_dir(path)
    _checked.add(path)
    return path


def child_tmp_env(path: Optional[str] = None) -> Dict[str, str]:
    """``TMPDIR``, ``TEMP`` and ``TMP`` for a child process started with an explicit environment."""
    d = path or tmp_dir()
    return {'TMPDIR': d, 'TEMP': d, 'TMP': d}


def apply_tmp_dir(sweep: bool = False) -> str:
    """Validate ``app.tmp_dir`` and make it this process's temp folder (``tempfile.tempdir`` and the
    environment children inherit). With ``sweep``, remove old leftovers (``sweep_tmp``). Raises
    TmpDirError for an unusable folder."""
    global _applied
    path = validate_tmp_dir(configured_tmp_dir())
    with _lock:
        tempfile.tempdir = path
        os.environ.update(child_tmp_env(path))
        _applied = path
    if sweep:
        try:
            removed = sweep_tmp()
            if removed:
                logger.info(f'  Temp folder: removed {len(removed)} old SAJHA leftover(s) from {path}')
        except Exception as e:                      # the sweep never stops start-up
            logger.warning(f'  Temp folder: sweep failed ({e})')
    return path


def apply_tmp_dir_or_exit(sweep: bool = False) -> str:
    """``apply_tmp_dir`` for a command-line entry point: an unusable folder exits with status 2."""
    try:
        return apply_tmp_dir(sweep=sweep)
    except TmpDirError as e:
        import sys
        print(f'error: {e}', file=sys.stderr)
        raise SystemExit(2)


def reset_for_tests() -> None:
    """Forget the applied folder (tests only); restores ``tempfile.tempdir`` to the system default."""
    global _applied
    with _lock:
        _applied = None
        tempfile.tempdir = None


# ── SAJHA's own entries ──────────────────────────────────────────

def tmp_prefix(kind: str) -> str:
    """The name prefix of a SAJHA temp entry: ``sajha-<kind>-p<pid>-`` (the sweep keeps an entry whose
    process still runs)."""
    return f'{PREFIX}{kind}-p{os.getpid()}-'


def register_tmp(path: str) -> str:
    """Remove ``path`` (file or folder) when the process exits normally; returns it."""
    with _lock:
        _registered.add(os.path.abspath(path))
    return path


def unregister_tmp(path: str) -> None:
    with _lock:
        _registered.discard(os.path.abspath(path))


def remove_tmp(path: str) -> None:
    """Delete one temp entry (and its SQLite ``-wal``/``-shm``/``-journal`` siblings), quietly."""
    unregister_tmp(path)
    _remove(path)
    for suffix in ('-wal', '-shm', '-journal'):
        if os.path.lexists(path + suffix):
            _remove(path + suffix)


def _remove(path: str) -> None:
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.debug(f'temp: could not remove {path}: {e}')


@atexit.register
def _cleanup_registered() -> None:
    with _lock:
        paths = list(_registered)
        _registered.clear()
    for p in paths:
        remove_tmp(p)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _newest_mtime(path: str, limit: int = 10000) -> float:
    """The newest modification time of ``path`` and (for a folder) anything under it; never follows links."""
    newest = os.lstat(path).st_mtime
    if not stat.S_ISDIR(os.lstat(path).st_mode):
        return newest
    seen = 0
    for root, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            seen += 1
            if seen > limit:
                return newest
            try:
                newest = max(newest, os.lstat(os.path.join(root, name)).st_mtime)
            except OSError:
                pass
    return newest


def max_age_hours() -> float:
    from sajha.core.config import _get
    try:
        return max(0.0, float(_get(MAX_AGE_KEY, str(DEFAULT_MAX_AGE_HOURS)) or DEFAULT_MAX_AGE_HOURS))
    except (TypeError, ValueError):
        return DEFAULT_MAX_AGE_HOURS


def sweep_tmp(max_age: Optional[float] = None, folder: Optional[str] = None,
              now: Optional[float] = None) -> List[str]:
    """Remove SAJHA's leftovers from the temp folder: entries named ``sajha-*`` whose newest
    modification is older than ``max_age`` hours (``app.tmp_max_age_hours``; 0 turns the sweep off),
    that this process has not registered and whose owning process (``-p<pid>-`` in the name) is gone.
    Anything not named ``sajha-*`` is never touched. Returns the removed paths."""
    hours = max_age_hours() if max_age is None else float(max_age)
    if hours <= 0:
        return []
    folder = folder or tmp_dir()
    cutoff = (time.time() if now is None else now) - hours * 3600
    with _lock:
        mine = set(_registered)
    removed: List[str] = []
    try:
        names = os.listdir(folder)
    except OSError:
        return removed
    for name in names:
        if not name.startswith(PREFIX) or name in KEEP:
            continue
        path = os.path.join(folder, name)
        if os.path.abspath(path) in mine:
            continue
        m = _PID.match(name)
        if m and _pid_alive(int(m.group(1))):
            continue
        try:
            if _newest_mtime(path) >= cutoff:
                continue
        except OSError:
            continue
        _remove(path)
        if not os.path.lexists(path):
            removed.append(path)
    return removed


# ── DuckDB ───────────────────────────────────────────────────────

def duckdb_temp_directory() -> str:
    """A spill folder of its own for one DuckDB database (two databases must not share one).
    DuckDB creates it only when it spills and removes it when the database closes."""
    return os.path.join(tmp_dir(), f'{tmp_prefix("duckdb")}{next(_counter)}')


def duckdb_connect(database: str = ':memory:', read_only: bool = False, config: Optional[Dict[str, Any]] = None):
    """``duckdb.connect`` with ``temp_directory`` under SAJHA's temp folder. DuckDB refuses to set
    ``temp_directory`` once external access is off, so ``enable_external_access: False`` and
    ``lock_configuration: True`` in ``config`` are applied right after the connection opens (before
    the caller gets it)."""
    import duckdb
    cfg = dict(config or {})
    no_external = 'enable_external_access' in cfg and not cfg.pop('enable_external_access')
    lock = bool(cfg.pop('lock_configuration', False))
    cfg.setdefault('temp_directory', duckdb_temp_directory())
    conn = duckdb.connect(database, read_only=read_only, config=cfg)
    try:
        if no_external:
            conn.execute('SET enable_external_access = false')
        if lock:
            conn.execute('SET lock_configuration = true')
    except Exception:
        conn.close()
        raise
    return conn
