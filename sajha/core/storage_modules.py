"""
SAJHA MCP Server — Studio-generated modules and scripts on the storage backend.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

MCP Studio writes a tool's JSON through the storage backend, but its Python implementation
(``sajha/tools/impl/<module>.py``) and a script tool's script (``config/scripts/<file>``) are
real files, because ``importlib`` and the sandbox need them on disk. On a cloud backend (s3,
azure, gcs) that used to mean a shared file system for every instance. Now:

* **Publish.** When a tool JSON is written through ``write_tool_config`` on a cloud backend,
  the module it names and its script are copied to the backend too: modules under
  ``studio/modules/<module>.py``, scripts under ``config/scripts/<file>``.
* **Materialise.** Before the tools registry loads a tool whose module is a Studio-generated
  one (``studio_*``, ``dbquery_*``, ``rest_*``, ``livelink_*``, ``powerbi_*``,
  ``powerbidax_*``, ``*_script_tool``), the module and script are fetched from the backend
  when the local copy is missing or older. A module missing from the package directory is
  written to ``<cache_dir>/studio_modules/``, which is added to the end of the
  ``sajha.tools.impl`` package path, so a file in the package always wins and nothing is
  written into the installed package on an instance that did not generate the tool.

On the local backend everything here is a no-op (the files already are the storage).
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MODULES_PREFIX = 'studio/modules'
SCRIPTS_PREFIX = 'config/scripts'
IMPL_PACKAGE = 'sajha.tools.impl'
GENERATED_PREFIXES = ('studio_', 'dbquery_', 'rest_', 'livelink_', 'powerbi_', 'powerbidax_')
GENERATED_SUFFIXES = ('_script_tool',)

_lock = threading.Lock()


def is_generated(leaf: str) -> bool:
    """A module name the Studio generators write (no built-in module uses these names)."""
    return bool(leaf) and leaf.isidentifier() and (leaf.startswith(GENERATED_PREFIXES)
                                                   or leaf.endswith(GENERATED_SUFFIXES))


def _object_backend():
    from sajha.core.storage import get_storage, LocalStorageBackend
    st = get_storage()
    return None if isinstance(st, LocalStorageBackend) else st


def _package_dir() -> Path:
    import sajha.tools.impl as pkg
    return Path(pkg.__file__).resolve().parent


def _scripts_dir() -> Path:
    from sajha.sandbox.tools import SCRIPTS_DIR
    return Path(SCRIPTS_DIR)


def cache_dir(backend=None) -> Path:
    backend = backend or _object_backend()
    if getattr(backend, 'cache_dir', None):
        base = Path(backend.cache_dir)
    else:
        from sajha.core.storage import default_cache_dir
        base = Path(default_cache_dir())
    return base / 'studio_modules'


def ensure_package_path(backend=None) -> Path:
    """Add the module cache to the end of ``sajha.tools.impl.__path__`` (idempotent)."""
    import sajha.tools.impl as pkg
    d = cache_dir(backend)
    d.mkdir(parents=True, exist_ok=True)
    if str(d) not in list(pkg.__path__):
        pkg.__path__.append(str(d))
        importlib.invalidate_caches()
    return d


# ── which module and script a config names ───────────────────────────────────

def _as_config(config_or_text: Any) -> Dict[str, Any]:
    if isinstance(config_or_text, dict):
        return config_or_text
    try:
        doc = json.loads(config_or_text)
        return doc if isinstance(doc, dict) else {}
    except (TypeError, ValueError):
        return {}


def module_leaf(config: Dict[str, Any]) -> Optional[str]:
    """The generated ``sajha.tools.impl`` module a tool config loads, if any."""
    impl = config.get('implementation')
    if isinstance(impl, dict) or isinstance(config.get('script'), dict) and not isinstance(impl, str):
        leaf = f"{config.get('name') or ''}_script_tool"
        return leaf if is_generated(leaf) else None
    if not isinstance(impl, str) or '.' not in impl:
        return None
    module = impl.rsplit('.', 1)[0]
    if not module.startswith(IMPL_PACKAGE + '.'):
        return None
    leaf = module[len(IMPL_PACKAGE) + 1:]
    return leaf if '.' not in leaf and is_generated(leaf) else None


def script_file(config: Dict[str, Any]) -> Optional[str]:
    info = config.get('script') if isinstance(config.get('script'), dict) else \
        (config.get('implementation') if isinstance(config.get('implementation'), dict) else None)
    if not info:
        return None
    name = info.get('script_file')
    if not name:
        from sajha.sandbox.tools import SCRIPT_EXTENSIONS
        ext = SCRIPT_EXTENSIONS.get(info.get('script_type') or 'bash')
        name = f"{config.get('name') or ''}{ext}" if ext and config.get('name') else None
    if not name or '/' in name or '\\' in name or name.startswith('.'):
        return None
    return name


# ── publish (the instance that generated the tool) ───────────────────────────

def publish_for_config(config_or_text: Any) -> list:
    """Copy the generated module and script a tool config names to the cloud backend. Returns
    the storage paths written (empty on the local backend or when there is nothing to copy)."""
    backend = _object_backend()
    if backend is None:
        return []
    config = _as_config(config_or_text)
    written = []
    leaf = module_leaf(config)
    if leaf:
        local = _package_dir() / f'{leaf}.py'
        if local.is_file():
            backend.write_bytes(f'{MODULES_PREFIX}/{leaf}.py', local.read_bytes())
            written.append(f'{MODULES_PREFIX}/{leaf}.py')
    name = script_file(config)
    if name:
        local = _scripts_dir() / name
        if local.is_file():
            backend.write_bytes(f'{SCRIPTS_PREFIX}/{name}', local.read_bytes())
            written.append(f'{SCRIPTS_PREFIX}/{name}')
    if written:
        logger.info(f'Published to the storage backend: {", ".join(written)}')
    return written


# ── materialise (every instance, before a load) ──────────────────────────────

def _refresh(backend, key: str, target: Path) -> bool:
    """Write object ``key`` to ``target`` when the target is missing or older and differs."""
    try:
        if not backend.exists(key):
            return False
        mtime = float(backend.get_modified_time(key) or 0)
        if target.is_file() and mtime and target.stat().st_mtime >= mtime:
            return False
        data = backend.read_bytes(key)
        if target.is_file() and target.read_bytes() == data:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name('.' + target.name + '.tmp')
        tmp.write_bytes(data)
        os.replace(tmp, target)
        if target.suffix == '.py':
            # bytecode is keyed by whole-second mtime and size: an edit of equal size within
            # the same second would otherwise import the old code
            try:
                import importlib.util
                Path(importlib.util.cache_from_source(str(target))).unlink(missing_ok=True)
            except Exception:
                pass
        return True
    except Exception as e:
        logger.warning(f'Could not materialise {key}: {e}')
        return False


def materialise_for_config(config: Dict[str, Any]) -> list:
    """Fetch the generated module and script a tool config needs from the cloud backend when
    the local copy is missing or stale. Returns the local files written."""
    backend = _object_backend()
    if backend is None:
        return []
    out = []
    with _lock:
        leaf = module_leaf(config)
        if leaf:
            in_package = _package_dir() / f'{leaf}.py'
            target = in_package if in_package.is_file() else ensure_package_path(backend) / f'{leaf}.py'
            if _refresh(backend, f'{MODULES_PREFIX}/{leaf}.py', target):
                out.append(str(target))
                importlib.invalidate_caches()
                mod = sys.modules.get(f'{IMPL_PACKAGE}.{leaf}')
                if mod is not None:
                    try:
                        importlib.reload(mod)
                    except Exception as e:
                        logger.warning(f'Reloading {leaf} after materialising failed: {e}')
        name = script_file(config)
        if name and _refresh(backend, f'{SCRIPTS_PREFIX}/{name}', _scripts_dir() / name):
            out.append(str(_scripts_dir() / name))
    if out:
        logger.info(f'Materialised from the storage backend: {", ".join(out)}')
    return out
