"""
SAJHA MCP Server — tool config files: the one authority for a tool's name and its file.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A tool config lives at ``<tools dir>/<name>.json`` (the root) or ``<tools dir>/<folder>/<name>.json``
(a tool folder), exactly one level deep. A deeper file is ignored and reported. Folders organise;
they never rename: a tool's name is its config's ``name`` (the file stem when the file has none).
A name may exist in one place only; two files with the same name load neither (the registry raises
``tools.duplicate:<name>``). Every piece of code that turns a tool name into a path asks the index
here; nothing builds ``config/tools/<name>.json`` by hand. Design: docs/architecture/Architecture.md
("Tool config files and folders").
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_PREFIX = 'config/tools'
FOLDER_MAX = 32
_FOLDER_RE = re.compile(r'^[a-z][a-z0-9_-]*$')


# ── folder names ─────────────────────────────────────────────────────────

def folder_problem(folder: str, check_tools: bool = True) -> Optional[str]:
    """Why ``folder`` may not name a tool folder (None: it may). The empty string is the root."""
    if folder in (None, ''):
        return None
    if not isinstance(folder, str):
        return 'a folder name must be text'
    if len(folder) > FOLDER_MAX:
        return f'folder name {folder!r} is longer than {FOLDER_MAX} characters'
    if not _FOLDER_RE.match(folder):
        return (f'folder name {folder!r} must start with a lowercase letter and use only lowercase '
                f'letters, digits, "_" or "-"')
    if '__' in folder:
        return f'folder name {folder!r} contains "__", which is reserved'
    if folder.lower() == UNFILED.lower():
        return f'folder name {folder!r} is reserved: it means the root of the tools directory'
    if check_tools and get_index().refresh().exists(folder):
        return f'folder name {folder!r} is the name of a tool; choose another'
    return None


#: The Folder field's explicit choice for the root of the tools directory (any case); same as empty.
UNFILED = 'Unfiled'


def is_unfiled(folder) -> bool:
    """True when ``folder`` is the explicit "Unfiled" choice (the root), as opposed to empty or a name."""
    return isinstance(folder, str) and folder.strip().strip('/').strip().lower() == UNFILED.lower()


def clean_folder(folder) -> str:
    """A folder as given by a form or an API: stripped of spaces and slashes ('' for the root, which
    "Unfiled" also names)."""
    s = str(folder or '').strip().strip('/').strip()
    return '' if s.lower() == UNFILED.lower() else s


def slug_folder(text) -> str:
    """A valid folder name made from free text (a category, a namespace), or '' when there is none."""
    s = re.sub(r'[^a-z0-9_-]+', '_', str(text or '').strip().lower())
    s = re.sub(r'_+', '_', s).strip('_-')
    s = re.sub(r'^[^a-z]+', '', s)[:FOLDER_MAX].rstrip('_-')
    return s if s and folder_problem(s, check_tools=False) is None else ''


# ── the target folder of new tools written by a generator ───────────────

_target: contextvars.ContextVar[str] = contextvars.ContextVar('sajha_tool_folder', default='')


@contextmanager
def writing_into(folder: str):
    """New tool configs written inside go into ``folder`` (validated first; '' is the root).
    Studio routes wrap a generator in this, so generators need not know about folders."""
    folder = clean_folder(folder)
    why = folder_problem(folder)
    if why:
        raise ValueError(why)
    token = _target.set(folder)
    try:
        yield folder
    finally:
        _target.reset(token)


def current_target() -> str:
    return _target.get()


# ── the index ────────────────────────────────────────────────────────────

def _storage():
    from sajha.core.storage import get_storage
    return get_storage()


def default_prefix() -> str:
    """The storage-relative tools directory: the live registry's, else ``config.tools.dir``."""
    try:
        from sajha.tools.tools_registry import ToolsRegistry
        reg = ToolsRegistry._instance
        prefix = getattr(reg, '_config_prefix', None) if reg is not None else None
        if prefix:
            return prefix
    except Exception:
        pass
    try:
        from sajha.core.config import _get
        prefix = str(_get('config.tools.dir', DEFAULT_PREFIX) or DEFAULT_PREFIX).replace('\\', '/').strip('/')
        return prefix if not PurePosixPath(prefix).is_absolute() and not prefix.startswith('..') else DEFAULT_PREFIX
    except Exception:
        return DEFAULT_PREFIX


def _name_of(config, rel: str) -> str:
    name = config.get('name') if isinstance(config, dict) else None
    return name if isinstance(name, str) and name else PurePosixPath(rel).stem


class ToolFileIndex:
    """Tool name <-> storage-relative path for one tools directory on one storage backend."""

    def __init__(self, prefix: str = DEFAULT_PREFIX, storage=None):
        self.prefix = prefix.strip('/')
        self._st = storage
        self._lock = threading.RLock()
        self._names: Dict[str, str] = {}        # rel -> tool name, for every file at an allowed depth
        self._deep: List[str] = []              # files nested deeper than one folder

    # paths
    def storage(self):
        return self._st if self._st is not None else _storage()

    def split(self, rel: str) -> Tuple[Optional[str], bool]:
        """(folder, allowed) of a path under the prefix: ('', True) root, ('x', True) one folder down,
        (None, False) deeper or outside."""
        rel = rel.replace('\\', '/')
        if not rel.startswith(self.prefix + '/'):
            return None, False
        parts = rel[len(self.prefix) + 1:].split('/')
        if len(parts) == 1:
            return '', True
        if len(parts) == 2:
            return parts[0], True
        return None, False

    def new_path(self, name: str, folder: str = '') -> str:
        folder = clean_folder(folder)
        return f'{self.prefix}/{folder}/{name}.json' if folder else f'{self.prefix}/{name}.json'

    # building
    def refresh(self, configs: Optional[Dict[str, object]] = None,
                rels: Optional[List[str]] = None) -> 'ToolFileIndex':
        """List the directory again (or take ``rels``, a listing the caller made). Files already known keep
        their name; new ones are read (or taken from ``configs``, rel -> parsed config)."""
        if rels is None:
            rels = self.storage().list_files(self.prefix, '*.json')
        names, deep = {}, []
        with self._lock:
            known = dict(self._names)
        for rel in rels:
            rel = rel.replace('\\', '/')
            if PurePosixPath(rel).name.startswith('.'):
                continue                         # an atomic write's temporary file
            folder, ok = self.split(rel)
            if not ok:
                deep.append(rel)
                continue
            if configs is not None and rel in configs:
                names[rel] = _name_of(configs[rel], rel)
            elif rel in known:
                names[rel] = known[rel]
            else:
                names[rel] = self._read_name(rel)
        with self._lock:
            self._names, self._deep = names, sorted(deep)
        return self

    def _read_name(self, rel: str) -> str:
        try:
            return _name_of(json.loads(self.storage().read_text(rel)), rel)
        except Exception:
            return PurePosixPath(rel).stem

    def note(self, rel: str, name: str) -> None:
        """A file was written or read: remember its name."""
        folder, ok = self.split(rel)
        if ok:
            with self._lock:
                self._names[rel] = name

    def forget(self, rel: str) -> None:
        with self._lock:
            self._names.pop(rel, None)

    # questions
    def name_at(self, rel: str) -> Optional[str]:
        with self._lock:
            return self._names.get(rel)

    def entries(self) -> List[Tuple[str, str, str]]:
        """(rel, name, folder) of every loadable-depth file."""
        with self._lock:
            items = sorted(self._names.items())
        return [(rel, name, self.split(rel)[0] or '') for rel, name in items]

    def by_name(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for rel, name, _ in self.entries():
            out.setdefault(name, []).append(rel)
        return out

    def paths_of(self, name: str) -> List[str]:
        with self._lock:
            return sorted(rel for rel, n in self._names.items() if n == name)

    def path_of(self, name: str) -> Optional[str]:
        """The file of ``name`` when exactly one file has it."""
        paths = self.paths_of(name)
        return paths[0] if len(paths) == 1 else None

    def folder_of(self, name: str) -> Optional[str]:
        rel = self.path_of(name)
        return None if rel is None else (self.split(rel)[0] or '')

    def exists(self, name: str) -> bool:
        return bool(self.paths_of(name))

    def duplicates(self) -> Dict[str, List[str]]:
        return {n: rels for n, rels in self.by_name().items() if len(rels) > 1}

    def too_deep(self) -> List[str]:
        with self._lock:
            return list(self._deep)

    def folders(self) -> List[str]:
        return sorted({f for _, _, f in self.entries() if f})

    def target_path(self, name: str, folder: Optional[str] = None) -> str:
        """Where a write of ``name`` goes: its current file when it has one (an edit never moves a
        tool), else ``folder`` (default: the writer's target folder, else the root)."""
        current = self.paths_of(name)
        if current:
            return current[0]
        return self.new_path(name, current_target() if folder is None else folder)


_indexes: Dict[str, Tuple[object, ToolFileIndex]] = {}
_indexes_lock = threading.Lock()


def get_index(prefix: Optional[str] = None, build: bool = True) -> ToolFileIndex:
    """The shared index of a tools directory on the current storage backend (one per backend).
    ``build=False``: a new index starts empty (the registry's loader fills it as it reads)."""
    prefix = (prefix or default_prefix()).strip('/')
    st = _storage()
    with _indexes_lock:
        held = _indexes.get(prefix)
        if held is None or held[0] is not st:
            idx = ToolFileIndex(prefix)
            if build:
                idx.refresh()
            _indexes[prefix] = (st, idx)
            return idx
        return held[1]


# ── helpers every writer uses ────────────────────────────────────────────

def name_taken(name: str) -> Optional[str]:
    """The path of a tool file named ``name`` anywhere (root or any folder), or None."""
    paths = get_index().refresh().paths_of(name)
    return paths[0] if paths else None


def config_path(name: str, folder: Optional[str] = None) -> str:
    """The storage-relative path to write ``name`` to (see ToolFileIndex.target_path)."""
    return get_index().target_path(name, folder)


def write_config(name: str, config_or_text, folder: Optional[str] = None) -> str:
    """Write a tool's config through the storage backend at its path; returns that path."""
    idx = get_index()
    rel = idx.target_path(name, folder)
    st = _storage()
    if isinstance(config_or_text, (dict, list)):
        st.write_json(rel, config_or_text)
    else:
        st.write_text(rel, config_or_text)
    idx.note(rel, name)
    return rel


def _drop_empty_folder(idx: ToolFileIndex, rel: str) -> None:
    """On local disk, remove a tool folder left empty (an object store has no folders to remove)."""
    from sajha.core.storage import LocalStorageBackend
    st = _storage()
    folder, ok = idx.split(rel)
    if not (ok and folder and isinstance(st, LocalStorageBackend)):
        return
    try:
        d = st.get_local_path(f'{idx.prefix}/{folder}')
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    except OSError:
        pass


def delete_config(name: str) -> bool:
    """Delete the file of ``name`` (every file, should there be duplicates). True if one was removed."""
    idx = get_index()
    removed = False
    for rel in idx.paths_of(name) or [idx.new_path(name)]:
        try:
            removed = bool(_storage().delete(rel)) or removed
        except Exception as e:
            logger.warning(f'tool files: cannot delete {rel}: {e}')
        idx.forget(rel)
        _drop_empty_folder(idx, rel)
    return removed


def files_matching(pattern: str) -> List[Tuple[str, str]]:
    """(name, rel) of every tool whose name matches the fnmatch ``pattern``."""
    import fnmatch
    return [(name, rel) for rel, name, _ in get_index().refresh().entries() if fnmatch.fnmatch(name, pattern)]


def move(names: Iterable[str], folder: str, dry_run: bool = False) -> List[Tuple[str, str, str]]:
    """Move tools into ``folder`` ('' the root): (name, old, new) per tool that moves. Refuses a name
    with more than one file, and a target path that already exists. The local backend renames the file
    (atomic); an object store writes the new object and then deletes the old one."""
    folder = clean_folder(folder)
    why = folder_problem(folder)
    if why:
        raise ValueError(why)
    idx = get_index().refresh()
    plan = []
    for name in names:
        paths = idx.paths_of(name)
        if not paths:
            raise ValueError(f'no tool named {name!r}')
        if len(paths) > 1:
            raise ValueError(f'tool {name!r} has more than one file ({", ".join(paths)}); remove one first')
        new = f'{idx.prefix}/{folder}/{PurePosixPath(paths[0]).name}' if folder else \
            f'{idx.prefix}/{PurePosixPath(paths[0]).name}'
        if new == paths[0]:
            continue
        if _storage().exists(new):
            raise ValueError(f'{new} already exists')
        plan.append((name, paths[0], new))
    if dry_run:
        return plan
    from sajha.core.storage import LocalStorageBackend
    st = _storage()
    for name, old, new in plan:
        if isinstance(st, LocalStorageBackend):
            src, dst = st.get_local_path(old), st.get_local_path(new)
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
        else:
            st.write_bytes(new, st.read_bytes(old))
            st.delete(old)
        idx.forget(old)
        idx.note(new, name)
        _drop_empty_folder(idx, old)
    return plan
