"""
SAJHA MCP Server — the report library page (docs/architecture/Reports.md §9).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``/reports/library`` lists the report definitions the caller may run; ``/reports/library/{name}``
shows one with its parameters and the runs the caller may see, each with its files;
``/api/reports/library/runs/{run_id}/{format}`` downloads a run's rendered file. Running a report
opens the report's tool (``report_<name>``) on the tool execute page, which builds the parameter
form from the tool's inputSchema.

The usage dashboard keeps ``/reports`` (sajha/routes/reporting_routes.py); in the menu it is
"Usage".

Who sees what: a definition is listed when it is enabled and the caller may run it (an
administrator; otherwise the definition's ``roles``, when it names any, must include one of the
caller's, and the caller must have access to the ``report_<name>`` tool). A run is shown, and its
files downloaded, only by its runner and administrators (sajha/reports/history.py ``may_see``).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from sajha.auth import AuthContext, require_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=['reports'])

MEDIA = {'markdown': 'text/markdown; charset=utf-8', 'html': 'text/html; charset=utf-8', 'pdf': 'application/pdf',
         'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
         'pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
         'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
LABELS = {'markdown': 'Markdown', 'html': 'HTML', 'pdf': 'PDF', 'xlsx': 'Excel', 'pptx': 'PowerPoint',
          'docx': 'Word'}


def _enabled() -> bool:
    try:
        from sajha.reports import settings
        return settings.enabled()
    except Exception:
        return False


def _definitions() -> Dict[str, Any]:
    try:
        from sajha.reports import store
        return store.definitions()
    except Exception as e:
        logger.warning(f'report library: definitions unavailable: {e}')
        return {}


def may_run(defn: Any, auth: AuthContext) -> bool:
    """May this caller run the report? The engine's rule (enabled, roles; sajha/reports/engine.py
    ``may_run``), and for a non-administrator access to the ``report_<name>`` tool."""
    try:
        from sajha.reports import engine
        if engine.may_run(defn, auth) is not None:
            return False
    except Exception as e:
        logger.debug(f'report library: may_run {getattr(defn, "name", "?")}: {e}')
        return False
    if auth.is_admin:
        return True
    try:
        return bool(auth.has_tool_access(defn.tool_name))
    except Exception:
        return False


def _tool_registered(name: str) -> bool:
    try:
        from sajha.app import tools_registry
        return bool(tools_registry and tools_registry.get_tool(name))
    except Exception:
        return False


def _runs(report: str, auth: AuthContext, limit: int = 100) -> List[Dict[str, Any]]:
    try:
        from sajha.reports import history
        return history.runs(report, caller=auth, limit=limit)
    except Exception as e:
        logger.debug(f'report library: runs of {report}: {e}')
        return []


def _card(defn: Any, auth: AuthContext) -> Dict[str, Any]:
    last = _runs(defn.name, auth, limit=1)
    tool = defn.tool_name
    return {'name': defn.name, 'title': defn.title or defn.name, 'description': defn.description,
            'owner': defn.owner, 'tags': list(defn.tags or []), 'classification': defn.classification,
            'formats': list(defn.formats or []), 'schedule': defn.schedule, 'tool': tool,
            'run_href': f'/tools/{tool}/execute' if _tool_registered(tool) else None,
            'detail_href': f'/reports/library/{defn.name}', 'last_run': last[0] if last else None}


def _user(auth: AuthContext) -> Dict[str, Any]:
    return {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles}


@router.get('/reports/library', name='report_library_page')
async def report_library_page(request: Request, auth: AuthContext = Depends(require_auth)):
    """The reports the caller may run, with run, history and last-run links."""
    from sajha.app import render
    q = (request.query_params.get('q') or '').strip().lower()
    enabled = _enabled()
    cards = []
    if enabled:
        for name, defn in sorted(_definitions().items()):
            if not may_run(defn, auth):
                continue
            hay = ' '.join([name, defn.title or '', defn.description or '', ' '.join(defn.tags or [])]).lower()
            if q and q not in hay:
                continue
            cards.append(_card(defn, auth))
    return render(request, 'reporting/report_library.html', {
        'user': _user(auth), 'is_admin': auth.is_admin, 'enabled': enabled, 'reports': cards, 'q': q})


@router.get('/reports/library/{name}', name='report_library_detail')
async def report_library_detail(name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    """One report: what it is, its parameters, and the caller's runs with their files."""
    from sajha.app import render
    defn = _definitions().get(name) if _enabled() else None
    if defn is None or not may_run(defn, auth):
        return render(request, 'common/error.html', {
            'error': 'Report Not Found', 'message': f'There is no report "{name}" that you may run.',
            'user': _user(auth)}, status_code=404)
    runs = _runs(name, auth)
    for r in runs:
        r['files'] = [{'format': f, 'label': LABELS.get(f, f),
                       'href': f'/api/reports/library/runs/{r["run_id"]}/{f}'} for f in r.get('formats') or []]
    params = [{'name': k, 'type': (v or {}).get('type', ''), 'description': (v or {}).get('description', ''),
               'default': (v or {}).get('default'), 'required': k in (defn.required or [])}
              for k, v in (defn.parameters or {}).items()]
    return render(request, 'reporting/report_library_detail.html', {
        'user': _user(auth), 'is_admin': auth.is_admin, 'report': _card(defn, auth), 'parameters': params,
        'sections': [{'id': s.get('id'), 'kind': s.get('kind'), 'title': s.get('title') or s.get('id')}
                     for s in defn.sections or []],
        'runs': runs})


@router.get('/api/reports/library/runs/{run_id}/{fmt}', name='report_run_download')
async def report_run_download(run_id: str, fmt: str, auth: AuthContext = Depends(require_auth)):
    """A rendered file of a run, as an attachment (the runner and administrators only)."""
    from fastapi import HTTPException
    from sajha.reports import history
    if fmt not in MEDIA:
        raise HTTPException(status_code=404, detail='unknown format')
    run = history.load(run_id)
    if run is None or not history.may_see(run, auth):
        raise HTTPException(status_code=404, detail='no such run')
    data = history.file_bytes(run_id, fmt)
    if data is None:
        raise HTTPException(status_code=404, detail=f'run {run_id} has no {fmt} file')
    try:
        from sajha import audit
        audit.record('report.download', actor={'user': auth.user_id}, resource={'type': 'report_run', 'name': run_id},
                     outcome='success', details={'format': fmt})
    except Exception:
        pass
    filename = f'{run_id}.{history.EXT[fmt]}'
    return Response(content=data, media_type=MEDIA[fmt],
                    headers={'Content-Disposition': f'attachment; filename="{filename}"',
                             'X-Content-Type-Options': 'nosniff'})
