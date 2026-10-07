"""
SAJHA MCP Studio — the planner editor (administrators only, LLM Tools §9.10 decision 6).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

    listing()          every planner the registry knows, the files it refused and why
    source(ref)        one planner file's text, its versions and its graph
    check(text)        the file as the registry would load it: the JSON Schema and the P-rules
                       (compile_planner + the registry's sub-planner link checks), and the graph
    save(text, by)     writes a new version: config/planners/<name>.yaml holds the newest, the
                       version it replaces is kept as <name>@<old version>.yaml (tools that pin
                       name@version keep working); an invalid file is never written

The registry keeps the last good version of a file that later fails validation (an edit made
outside the editor), so running tools keep working; the editor shows those load problems.
Reference: docs/architecture/Planner Reference.md §2 and §14 (the editor).
"""

from __future__ import annotations

import json
import logging
from pathlib import PurePosixPath
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

MAX_TEXT = 200_000


class EditorError(ValueError):
    def __init__(self, message: str, status: int = 400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def _registry():
    from sajha.ai.planners_engine import get_registry
    return get_registry()


def _diag(d) -> Dict[str, Any]:
    return d.to_dict() if hasattr(d, 'to_dict') else dict(d)


# ── the graph ────────────────────────────────────────────────────────

def graph(doc: Any) -> Dict[str, Any]:
    """Nodes and edges of a graph planner, read from the document itself (so a file with errors
    still draws): every outcome, ``next``, ``else`` and ``on_exhausted``; bounded edges carry
    their ``max_visits``. Levels are breadth-first distances from ``start``."""
    if not isinstance(doc, dict) or doc.get('kind', 'graph') != 'graph' or not isinstance(doc.get('stages'), dict):
        return {'nodes': [], 'edges': [], 'start': None}
    stages = doc['stages']
    start = doc.get('start') if isinstance(doc.get('start'), str) else None
    edges: List[Dict[str, Any]] = []

    def add(src: str, t: Any, label: str, kind: str = 'outcome') -> None:
        if not isinstance(t, dict):
            return
        nxt = str(t.get('next') or '')
        mv = t.get('max_visits')
        edges.append({'from': src, 'to': nxt, 'label': label, 'kind': kind,
                      'when': str(t['when']) if t.get('when') is not None else None,
                      'bounded': mv is not None, 'max_visits': mv,
                      'on_exhausted': str(t['on_exhausted']) if t.get('on_exhausted') else None,
                      'dangling': nxt not in stages})
        if t.get('on_exhausted'):
            edges.append({'from': src, 'to': str(t['on_exhausted']), 'label': f'{label} exhausted',
                          'kind': 'exhausted', 'when': None, 'bounded': False, 'max_visits': None,
                          'on_exhausted': None, 'dangling': str(t['on_exhausted']) not in stages})

    for sid, raw in stages.items():
        if not isinstance(raw, dict):
            continue
        if 'next' in raw:
            add(str(sid), {'next': raw['next']}, 'next', 'next')
        for okey, tv in (raw.get('outcomes') or {}).items() if isinstance(raw.get('outcomes'), dict) else ():
            for i, t in enumerate(tv if isinstance(tv, list) else [tv]):
                add(str(sid), t, str(okey) if not isinstance(tv, list) or len(tv) == 1 else f'{okey} [{i}]')
        if isinstance(raw.get('else'), dict):
            add(str(sid), raw['else'], 'else', 'else')
    # breadth-first levels from start; unreachable stages go last
    level: Dict[str, int] = {}
    if start in stages:
        level[start] = 0
        queue = [start]
        while queue:
            u = queue.pop(0)
            for e in edges:
                if e['from'] == u and e['to'] in stages and e['to'] not in level:
                    level[e['to']] = level[u] + 1
                    queue.append(e['to'])
    top = max(level.values(), default=-1) + 1
    nodes = []
    for sid, raw in stages.items():
        t = raw.get('type') if isinstance(raw, dict) else None
        nodes.append({'id': str(sid), 'type': str(t or '?'), 'start': sid == start,
                      'terminal': t in ('answer', 'fail'), 'level': level.get(str(sid), top),
                      'reachable': str(sid) in level,
                      'description': str((raw or {}).get('description') or '') if isinstance(raw, dict) else ''})
    for e in edges:
        e['back'] = e['to'] in level and e['from'] in level and level[e['to']] <= level[e['from']]
    return {'nodes': nodes, 'edges': edges, 'start': start}


# ── checking a file ──────────────────────────────────────────────────

def parse(text: str) -> Any:
    if not isinstance(text, str) or not text.strip():
        raise EditorError('the planner file is empty')
    if len(text) > MAX_TEXT:
        raise EditorError(f'the planner file is larger than {MAX_TEXT} characters')
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, 'problem_mark', None)
        where = f' (line {mark.line + 1}, column {mark.column + 1})' if mark is not None else ''
        raise EditorError(f'P001 not a planner file: YAML does not parse{where}: '
                          f'{getattr(e, "problem", None) or e}')


def check(text: str) -> Dict[str, Any]:
    """Validate a planner file exactly as the registry would load it."""
    from sajha.ai.planners_engine.model import PlannerError, compile_planner
    from sajha.ai.planners_engine.registry import _check_alias, _check_prompt
    reg = _registry()
    try:
        doc = parse(text)
    except EditorError as e:
        return {'valid': False, 'errors': [{'code': 'P001', 'level': 'error', 'location': '', 'message': str(e)}],
                'warnings': [], 'graph': graph(None), 'doc': None, 'name': None, 'version': None}
    name = doc.get('name') if isinstance(doc, dict) else None
    version = doc.get('version') if isinstance(doc, dict) else None
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    pdef = None
    try:
        pdef = compile_planner(doc, file_stem=str(name) if isinstance(name, str) else None,
                               ceilings=reg.settings.ceilings(), check_alias=_check_alias,
                               check_prompt=_check_prompt, file=f'{reg.dir}/{name}.yaml')
        warnings.extend(_diag(d) for d in pdef.warnings)
    except PlannerError as e:
        for d in e.diagnostics:
            (errors if d.level == 'error' else warnings).append(_diag(d))
    if pdef is not None and pdef.kind == 'graph':
        for d in reg.link(pdef, {}):                 # sub-planner references (P033 P034 P035), P071
            (errors if d.level == 'error' else warnings).append(_diag(d))
    if isinstance(name, str) and not errors:
        try:
            from sajha.ai.planners_engine.registry import PY_BUILTINS
            py = reg._python_registrations()
            if name in py and name not in PY_BUILTINS:
                errors.append({'code': 'P005', 'level': 'error', 'location': 'name',
                               'message': f'{name} is also registered as a Python planner'})
        except Exception:
            pass
    return {'valid': not errors, 'errors': errors, 'warnings': warnings, 'graph': graph(doc),
            'doc': json.loads(json.dumps(doc, default=str)) if isinstance(doc, dict) else None,
            'name': name, 'version': version, 'kind': (doc or {}).get('kind', 'graph') if isinstance(doc, dict) else None}


# ── reading ──────────────────────────────────────────────────────────

def _files() -> List[str]:
    reg = _registry()
    reg.maybe_reload()
    return reg._listing()


def listing() -> Dict[str, Any]:
    """Planners (the newest version of each, with every version kept) and the files the registry refused."""
    reg = _registry()
    planners = reg.describe()
    problems = reg.problems()
    refused = []
    for fname, diags in sorted(reg.errors.items()):
        stem = fname.rsplit('.', 1)[0]
        name = stem.split('@')[0]
        kept = sorted(reg.files.get(name, {}))
        refused.append({'file': fname, 'name': name, 'errors': [_diag(d) for d in diags],
                        'last_good': kept, 'in_use': bool(kept)})
    return {'planners': planners, 'refused': refused, 'problems': problems, 'dir': reg.dir,
            'default': reg.settings.default, 'dry_run_model': reg.settings.dry_run_model,
            'files': [PurePosixPath(p).name for p in _files()]}


def _file_for(name: str, version: Optional[str]) -> Optional[str]:
    reg = _registry()
    entries = reg.files.get(name, {})
    if version and version in entries and entries[version].file:
        return entries[version].file
    if not version and entries:
        from sajha.ai.planners_engine.model import semver_key
        return entries[max(entries, key=semver_key)].file
    for p in _files():               # a refused file is still readable
        stem = PurePosixPath(p).name.rsplit('.', 1)[0]
        if stem == (f'{name}@{version}' if version else name):
            return p
    return None


def source(ref: str) -> Dict[str, Any]:
    from sajha.ai.planners_engine.model import parse_ref
    try:
        name, version = parse_ref(ref)
    except ValueError as e:
        raise EditorError(str(e), 404)
    reg = _registry()
    reg.maybe_reload()
    path = _file_for(name, version)
    if path is None:
        py = reg._python_registrations()
        if name in py:
            raise EditorError(f'{name} is a Python planner ({py[name].__module__}:{py[name].__name__}); '
                              f'it has no file to edit', 404)
        raise EditorError(f'no planner file for {ref}', 404)
    text = reg.storage().read_text(path)
    out = check(text)
    from sajha.ai.planners_engine.model import semver_key
    out.update({'file': PurePosixPath(path).name, 'text': text,
                'versions': sorted(reg.files.get(name, {}), key=semver_key),
                'load_errors': [_diag(d) for d in reg.errors.get(PurePosixPath(path).name, [])]})
    return out


# ── saving a new version ─────────────────────────────────────────────

def save(text: str, by: str = '') -> Dict[str, Any]:
    """Write a new planner version. Refuses invalid files, a version that exists already, and an
    edit that keeps the version (bump it: tools that pin name@version must keep what they tested)."""
    from sajha.ai.planners_engine.model import semver_key
    result = check(text)
    if not result['valid']:
        raise EditorError('the planner has errors; nothing was written', 400, check=result)
    name, version = result['name'], result['version']
    reg = _registry()
    st = reg.storage()
    reg.maybe_reload()
    main = f'{reg.dir}/{name}.yaml'
    kept = f'{reg.dir}/{name}@{version}.yaml'
    existing = reg.files.get(name, {})
    if version in existing or st.exists(kept):
        current = existing.get(version)
        if current is not None and current.doc == result['doc']:
            return {**result, 'saved': False, 'file': PurePosixPath(current.file).name,
                    'message': f'{name}@{version} is unchanged'}
        raise EditorError(f'{name}@{version} exists already; change "version" to save a new one '
                          f'(P070: tools that pin {name}@{version} keep the file they were tested with)', 409)
    moved = None
    if st.exists(main):
        try:
            old = yaml.safe_load(st.read_text(main))
            old_version = str(old.get('version')) if isinstance(old, dict) and old.get('version') else None
        except Exception:
            old_version = None
        if old_version and old_version != version:
            if semver_key(version) < semver_key(old_version):
                # an older version than the newest file: keep it beside, leave the newest in place
                st.write_text(kept, _with_header(text, by))
                return _after_save(name, version, PurePosixPath(kept).name, None, by)
            target = f'{reg.dir}/{name}@{old_version}.yaml'
            if not st.exists(target):
                st.write_text(target, st.read_text(main))
                moved = PurePosixPath(target).name
    st.write_text(main, _with_header(text, by))
    return _after_save(name, version, PurePosixPath(main).name, moved, by)


def _with_header(text: str, by: str) -> str:
    return text if text.endswith('\n') else text + '\n'


def _after_save(name: str, version: str, fname: str, moved: Optional[str], by: str) -> Dict[str, Any]:
    reg = _registry()
    reg.invalidate()
    reg.load()
    errs = [_diag(d) for d in reg.errors.get(fname, [])]
    _audit(by, 'save', {'planner': f'{name}@{version}', 'file': fname, 'kept': moved, 'load_errors': len(errs)})
    msg = f'Saved {name}@{version} as {fname}' + (f'; the previous version is kept as {moved}' if moved else '')
    return {'saved': True, 'file': fname, 'kept': moved, 'name': name, 'version': version,
            'load_errors': errs, 'message': msg}


def _audit(by: str, what: str, details: Dict[str, Any]) -> None:
    try:
        from sajha.core.audit import AuditLogger
        AuditLogger().config_changed(f'studio.planner.{what}', by_user=by or None,
                                     details=json.dumps(details, default=str)[:2000])
    except Exception as e:
        logger.debug(f'planner editor audit: {e}')
