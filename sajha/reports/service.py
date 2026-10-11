"""
SAJHA MCP Server — Reports: the generated ``report_<name>`` tools.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

* :func:`tool_config`  the generated config of one definition (planner-friendly description,
  the definition's parameters as the inputSchema, read-only annotations)
* :func:`sync`         make the ``report_*`` configs in the tool folder ``reports`` match the
  enabled definitions: write, hot-load, remove. A generated config carries
  ``"report": {"name", "definition_hash"}``; only such configs are ever changed or removed, so the
  fixed tools (``report_list`` ...) and any other tool are left alone. A name already taken by a
  tool that is not a generated report tool is refused with the warning notice
  ``reports.name_conflict:<tool>``.
* :func:`init_reports` start-up: load the definitions, sync, and keep syncing every
  ``reports.reload_seconds`` while definitions change (hot reload).

Tool configs are written through the storage backend like the data connectors' (the registry
plumbing is shared with sajha/connectors/service.py).
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional

from sajha.reports import settings, store
from sajha.reports.model import FORMATS, ReportDefinition

logger = logging.getLogger(__name__)

FOLDER = 'reports'
IMPLEMENTATION = 'sajha.reports.tools.ReportTool'
NOTICE_CONFLICT = 'reports.name_conflict:'
OUTPUT_SCHEMA = {
    'type': 'object', 'required': ['run_id', 'report', 'status', 'markdown'],
    'properties': {
        'run_id': {'type': 'string', 'description': 'The run id: report_render, report_compare and report_history use it'},
        'report': {'type': 'string'}, 'title': {'type': 'string'},
        'status': {'type': 'string', 'enum': ['succeeded', 'partial', 'failed'],
                   'description': 'partial: some sections were not permitted, unavailable or failed'},
        'classification': {'type': 'string'}, 'parameters': {'type': 'object'}, 'started_at': {'type': 'string'},
        'files': {'type': 'object', 'description': 'format -> stored file path'},
        'files_unavailable': {'type': 'object', 'description': 'format -> why it could not be made'},
        'previous_run_id': {'type': ['string', 'null']},
        'warnings': {'type': 'array', 'items': {'type': 'string'}},
        'sections': {'type': 'array', 'items': {'type': 'object'}},
        'markdown': {'type': 'string', 'description': 'The whole report as Markdown'},
    }}
_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _example(schema: Dict[str, Any]) -> str:
    ex = (schema.get('examples') or [{}])[0]
    return json.dumps(ex)


#: a generated description stays within SAJHA Net's 1024 characters together with the folder's domain text
MAX_DESCRIPTION = 700


def tool_config(d: ReportDefinition) -> Dict[str, Any]:
    schema = d.input_schema()
    params = [f'{k}{"*" if k in d.required else ""}' for k in d.parameters]
    tools = sorted({c['tool'] for c in d.calls()})
    rest = ('\nReturns: run_id, status (succeeded, partial or failed), the report as markdown, files by '
            'format, sections (KPIs, tables, each section\'s source).')
    rest += f'\nInputs (* required): {", ".join(params) if params else "none"}; formats (default {", ".join(d.formats)}).'
    if tools:
        rest += f'\nSources (called as you): {", ".join(tools)}.'
    rest += f'\nExample: {_example(schema)}'
    about = d.description.strip()
    head = f'Runs the report "{d.title}"' + (f': {about}' if about else '.')
    room = MAX_DESCRIPTION - len(rest)
    if len(head) > room:
        head = head[:max(40, room - 3)].rstrip() + '...'
    desc = head + rest
    title = f'Report: {d.title}'[:120]
    return {
        'name': d.tool_name, 'implementation': IMPLEMENTATION, 'title': title, 'description': desc,
        'version': '1.0.0', 'enabled': True, 'inputSchema': schema, 'outputSchema': OUTPUT_SCHEMA,
        'annotations': {'title': title, 'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': False,
                        'openWorldHint': True},
        'metadata': {'author': 'Reports', 'category': 'Reports', 'tags': ['report', d.name] + list(d.tags),
                     'source': 'report', 'definition': d.source},
        'report': {'name': d.name, 'definition_hash': d.digest},
    }


def desired_configs() -> Dict[str, Dict[str, Any]]:
    if not settings.enabled():
        return {}
    return {d.tool_name: tool_config(d) for d in store.definitions().values() if d.enabled}


def _is_generated(cfg: Any) -> bool:
    return isinstance(cfg, dict) and isinstance(cfg.get('report'), dict) and cfg.get('implementation') == IMPLEMENTATION


def _owned(registry) -> List[str]:
    names = set()
    if registry is not None:
        for n, cfg in list((getattr(registry, 'tool_configs', {}) or {}).items()):
            if _is_generated(cfg):
                names.add(n)
    try:
        from sajha.connectors.service import _stored
        from sajha.tools.tool_files import files_matching
        for n, _rel in files_matching('report_*'):
            if _is_generated(_stored(n)):
                names.add(n)
    except Exception:
        pass
    return sorted(names)


def _conflict(name: str, registry) -> bool:
    """A tool of this name exists and is not a generated report tool."""
    from sajha.connectors.service import _stored
    if registry is not None:
        cfg = (getattr(registry, 'tool_configs', {}) or {}).get(name)
        if cfg is not None:
            return not _is_generated(cfg)
        if name in (getattr(registry, 'tools', {}) or {}):
            return True
    cur = _stored(name)
    return cur is not None and not _is_generated(cur)


def sync(registry=None) -> Dict[str, Any]:
    from sajha.connectors.service import _bulk, _load, _reindex, _remove, _stored, _unload
    from sajha.core.storage import write_tool_config
    desired = desired_configs()
    owned = _owned(registry)
    added, updated, removed, kept, failed, conflicts = [], [], [], [], [], {}
    with _bulk(registry):
        for name in owned:
            if name not in desired:
                _unload(registry, name)
                _remove(name)
                _unload(registry, name)
                removed.append(name)
        for name, cfg in desired.items():
            if _conflict(name, registry):
                conflicts[name] = cfg['report']['name']
                continue
            current = _stored(name)
            if current == cfg:
                if registry is not None and name not in registry.tools:
                    ok, err = _load(registry, name)
                    if not ok:
                        failed.append({'name': name, 'error': err})
                        continue
                kept.append(name)
                continue
            try:
                write_tool_config(f'{name}.json', cfg, folder=FOLDER)
            except Exception as e:
                failed.append({'name': name, 'error': f'could not write the config: {e}'})
                continue
            _unload(registry, name)
            ok, err = _load(registry, name)
            if not ok:
                failed.append({'name': name, 'error': err})
                continue
            (updated if current is not None else added).append(name)
    if added or updated or removed:
        _reindex(registry)
    try:
        from sajha.notices.sources import reconcile
        reconcile(NOTICE_CONFLICT, {f'{NOTICE_CONFLICT}{n}': {
            'severity': 'warning', 'source': 'reports', 'title': f'Report {r} has no tool: {n} is taken',
            'detail': f'A tool named {n} already exists and is not a generated report tool, so the report {r} is '
                      f'not published as a tool. Rename the report or the other tool. report_run still runs it.',
            'link': '/help/guides/Reports.md'} for n, r in conflicts.items()})
    except Exception as e:
        logger.debug(f'reports notices: {e}')
    return {'added': added, 'updated': updated, 'removed': removed, 'unchanged': kept, 'failed': failed,
            'conflicts': sorted(conflicts), 'tools': sorted(desired)}


def _format_notices() -> None:
    """One info notice per format a definition asks for that this server cannot make."""
    from sajha.reports import render
    wanted = {f for d in store.definitions().values() if d.enabled for f in d.formats}
    desired = {}
    for f in sorted(wanted & set(FORMATS)):
        why = render.unavailable(f)
        if why:
            desired[f'reports.format_unavailable:{f}'] = {
                'severity': 'info', 'source': 'reports', 'title': f'Reports: {f.upper()} is not offered',
                'detail': f'{why}. Reports that ask for it are rendered in their other formats.',
                'link': '/help/guides/Reports.md'}
    try:
        from sajha.notices.sources import reconcile
        reconcile('reports.format_unavailable:', desired)
    except Exception as e:
        logger.debug(f'reports notices: {e}')


def _watch(registry) -> None:
    seen = store.version()
    while not _stop.wait(max(1, settings.reload_seconds() or 5)):
        try:
            v = store.version()
            if v != seen:
                seen = v
                out = sync(registry)
                _format_notices()
                logger.info(f'Reports: definitions changed; tools added {out["added"]}, updated {out["updated"]}, '
                            f'removed {out["removed"]}')
        except Exception as e:
            logger.debug(f'reports watch: {e}')


def init_reports(registry) -> Dict[str, Any]:
    """Start-up: load definitions, sync the generated tools, raise format notices, start the watcher."""
    global _thread
    store.scan(force=True)
    out = sync(registry)
    _format_notices()
    n = len(store.definitions())
    logger.info(f'  Reports: {n} definition(s), {len(out["tools"])} report tool(s)'
                + (f'; refused files {len(store.errors())}' if store.errors() else ''))
    if settings.reload_seconds() > 0 and (_thread is None or not _thread.is_alive()):
        _stop.clear()
        _thread = threading.Thread(target=_watch, args=(registry,), name='reports-watch', daemon=True)
        _thread.start()
    return out


def shutdown_reports() -> None:
    _stop.set()
