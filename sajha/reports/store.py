"""
SAJHA MCP Server — report definitions on disk: load, validate, hot-reload, notices.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Definitions are ``*.yaml``, ``*.yml`` or ``*.json`` files directly under ``reports.dir``
(default ``config/reports``), read through the storage backend. :func:`definitions` rescans at
most every ``reports.reload_seconds`` and reparses only files whose modification time changed.

Notices (docs/architecture/System Notices.md):

* ``reports.definition:<file>`` (warning): the file was refused; the detail names every problem.
* ``reports.duplicate:<name>`` (warning): two files define one report; neither loads.
* ``reports.missing_tools:<name>`` (info): the report calls tools this server does not have; those
  sections render "unavailable" and the report still runs.
"""

from __future__ import annotations

import logging
import posixpath
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

from sajha.reports import settings
from sajha.reports.model import ReportDefinition, ReportDefinitionError, check_sub_reports, missing_tools, parse

logger = logging.getLogger(__name__)

NOTICE_FILE = 'reports.definition:'
NOTICE_DUP = 'reports.duplicate:'
NOTICE_MISSING = 'reports.missing_tools:'
_EXTS = ('.yaml', '.yml', '.json')


class _State:
    def __init__(self):
        self.lock = threading.RLock()
        self.files: Dict[str, Tuple[float, Optional[ReportDefinition], List[str]]] = {}   # rel -> (mtime, def, problems)
        self.defs: Dict[str, ReportDefinition] = {}
        self.errors: Dict[str, List[str]] = {}        # file or report name -> problems
        self.missing: Dict[str, List[str]] = {}       # report -> tools not on this server
        self.scanned_at = 0.0
        self.directory = ''
        self.version = 0                              # bumps whenever the set of definitions changes


_state = _State()
#: tests may replace how a tool's existence is checked (default: the tools registry)
_tool_exists: Optional[Callable[[str], bool]] = None


def _storage():
    from sajha.reports.files import backend   # absolute dirs: plain pathlib
    return backend()


def _registry_exists(name: str) -> bool:
    if _tool_exists is not None:
        return _tool_exists(name)
    try:
        from sajha.tools.tools_registry import ToolsRegistry
        reg = ToolsRegistry._instance if hasattr(ToolsRegistry, '_instance') else None
        if reg is None:
            return True                 # no registry yet (a CLI or a test): do not warn
        return name in (getattr(reg, 'tools', {}) or {}) or name in (getattr(reg, 'tool_configs', {}) or {}) \
            or name in (getattr(reg, 'skipped_tools', {}) or {})
    except Exception:
        return True


def set_tool_exists(fn: Optional[Callable[[str], bool]]) -> None:
    global _tool_exists
    _tool_exists = fn


def reset() -> None:
    """Forget every loaded definition (tests; a changed ``reports.dir``)."""
    global _state
    _state = _State()


def _list(directory: str) -> List[str]:
    st = _storage()
    try:
        files = st.list_files(directory, '*')
    except Exception as e:
        logger.debug(f'reports: cannot list {directory}: {e}')
        return []
    out = []
    for f in files:
        rel = f.replace('\\', '/')
        if posixpath.dirname(rel).rstrip('/') != directory.rstrip('/'):
            continue                    # one level only
        if rel.endswith(_EXTS):
            out.append(rel)
    return sorted(out)


def _parse_file(rel: str) -> Tuple[Optional[ReportDefinition], List[str]]:
    try:
        text = _storage().read_text(rel)
    except Exception as e:
        return None, [f'cannot read: {e}']
    try:
        if rel.endswith('.json'):
            import json
            try:
                doc = json.loads(text)
            except ValueError as e:
                return None, [f'not valid JSON: {e}']
        else:
            from sajha.reports.model import load_text
            doc = load_text(text, rel)
        return parse(doc, rel, settings.max_sections()), []
    except ReportDefinitionError as e:
        return None, e.problems


def _notice(nid: str, severity: str, title: str, detail: str) -> None:
    try:
        from sajha import notices
        notices.raise_notice(nid, severity=severity, source='reports', title=title, detail=detail,
                             link='/help/guides/Reports.md')
    except Exception:
        pass


def _reconcile(prefix: str, desired: Dict[str, Dict[str, str]]) -> None:
    try:
        from sajha.notices.sources import reconcile
        reconcile(prefix, {k: dict(v, source='reports', link='/help/guides/Reports.md') for k, v in desired.items()})
    except Exception as e:
        logger.debug(f'reports notices: {e}')


def scan(force: bool = False) -> int:
    """Rescan the definitions directory; returns the version (bumped when the set changed)."""
    with _state.lock:
        directory = settings.reports_dir()
        now = time.monotonic()
        if not force and directory == _state.directory and now - _state.scanned_at < settings.reload_seconds() \
                and _state.scanned_at:
            return _state.version
        if directory != _state.directory:
            _state.files.clear()
        _state.directory = directory
        _state.scanned_at = now
        st = _storage()
        seen = set()
        for rel in _list(directory):
            seen.add(rel)
            try:
                mtime = st.get_modified_time(rel)
            except Exception:
                mtime = -1.0
            cur = _state.files.get(rel)
            if cur is not None and cur[0] == mtime and mtime >= 0:
                continue
            d, problems = _parse_file(rel)
            _state.files[rel] = (mtime, d, problems)
        for rel in list(_state.files):
            if rel not in seen:
                del _state.files[rel]
        defs: Dict[str, ReportDefinition] = {}
        by_name: Dict[str, List[str]] = {}
        errors: Dict[str, List[str]] = {}
        for rel, (_m, d, problems) in sorted(_state.files.items()):
            if d is None:
                errors[rel] = problems
                continue
            by_name.setdefault(d.name, []).append(rel)
            defs[d.name] = d
        dups = {n: rels for n, rels in by_name.items() if len(rels) > 1}
        for n in dups:
            defs.pop(n, None)
        for n, why in check_sub_reports(defs).items():
            errors[defs[n].source] = [why]
        for n in list(defs):
            if defs[n].source in errors:
                defs.pop(n)
        missing = {n: missing_tools(d, _registry_exists) for n, d in defs.items()}
        missing = {n: m for n, m in missing.items() if m}
        _reconcile(NOTICE_FILE, {f'{NOTICE_FILE}{posixpath.basename(rel)}': {
            'severity': 'warning', 'title': f'Report definition {posixpath.basename(rel)} was refused',
            'detail': f'{rel}: ' + '; '.join(p) + '. The report is not available until the file is fixed.'}
            for rel, p in errors.items()})
        _reconcile(NOTICE_DUP, {f'{NOTICE_DUP}{n}': {
            'severity': 'warning', 'title': f'Report {n} is defined twice',
            'detail': f'{", ".join(rels)} both define report {n}; neither is loaded. Remove one.'}
            for n, rels in dups.items()})
        _reconcile(NOTICE_MISSING, {f'{NOTICE_MISSING}{n}': {
            'severity': 'info', 'title': f'Report {n} calls tools this server does not have',
            'detail': f'{", ".join(m)}: those sections render "unavailable" and the report still runs.'}
            for n, m in missing.items()})
        errors.update({f'duplicate:{n}': [f'defined in {", ".join(r)}'] for n, r in dups.items()})
        changed = (set(defs) != set(_state.defs)
                   or any(defs[n].digest != _state.defs[n].digest for n in defs if n in _state.defs))
        _state.defs, _state.errors, _state.missing = defs, errors, missing
        if changed:
            _state.version += 1
        return _state.version


def definitions() -> Dict[str, ReportDefinition]:
    """Every loaded definition (enabled or not), by name."""
    scan()
    return dict(_state.defs)


def get(name: str) -> Optional[ReportDefinition]:
    return definitions().get(name)


def errors() -> Dict[str, List[str]]:
    scan()
    return dict(_state.errors)


def missing() -> Dict[str, List[str]]:
    scan()
    return dict(_state.missing)


def version() -> int:
    return scan()
