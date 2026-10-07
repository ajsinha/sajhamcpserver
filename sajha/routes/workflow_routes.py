"""
SAJHA MCP Server — workflow routes: the Workflows page and /api/workflows.

* ``GET  /workflows``                               the page: list, editor (form, DAG, JSON/YAML), runs
* ``GET  /api/workflows``                           your workflows (administrators: all)
* ``POST /api/workflows``                           create or update (JSON body, or YAML/JSON text in ``text``)
* ``POST /api/workflows/validate``                  check a definition without saving it
* ``GET|PUT|DELETE /api/workflows/{name}``          one definition (``?format=yaml``)
* ``POST /api/workflows/{name}/enable|disable``
* ``POST /api/workflows/{name}/runs``               manual run (``Idempotency-Key`` header; ``wait`` seconds)
* ``GET  /api/workflows/{name}/runs``               run history
* ``GET  /api/workflows/runs/{id}``                 one run with its step timeline
* ``POST /api/workflows/runs/{id}/cancel``          cancel
* ``POST /api/workflows/runs/{id}/rerun``           re-run (``from_step``; default the first failed step)
* ``POST /api/workflows/{name}/hooks/{trigger}``    inbound webhook (no session: HMAC-signed)

Design: docs/architecture/Workflows.md. Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool

from sajha.auth import AuthContext, require_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=['workflows'])


def _svc():
    from sajha.workflows import get_service
    return get_service()


def _unavailable():
    return JSONResponse({'error': 'workflows are not available on this server (workflows.enabled, or the '
                                  'database tables are missing)'}, status_code=503)


def _wf_public(wf: Dict[str, Any], reveal: bool = False) -> Dict[str, Any]:
    from sajha.workflows.model import public
    d = public(wf['definition'], reveal_secrets=reveal)
    return {'name': wf['name'], 'description': wf['description'], 'owner': wf['owner'], 'enabled': wf['enabled'],
            'published': wf['published'], 'version': wf['version'], 'created_at': wf['created_at'],
            'updated_at': wf['updated_at'], 'updated_by': wf['updated_by'], 'definition': d,
            'triggers': [{'id': t['id'], 'type': t['type'], 'enabled': t.get('enabled', True)}
                         for t in d.get('triggers', [])],
            'steps': len(d.get('steps', []))}


def _run_public(run: Dict[str, Any], full: bool = False) -> Dict[str, Any]:
    out = {k: v for k, v in run.items() if k not in ('definition',)}
    if not full:
        out.pop('steps', None)
    return out


def _error(e: Exception):
    from sajha.workflows.model import WorkflowError
    if isinstance(e, PermissionError):
        return JSONResponse({'error': str(e)}, status_code=403)
    if isinstance(e, KeyError):
        return JSONResponse({'error': f'not found: {e.args[0] if e.args else ""}'}, status_code=404)
    if isinstance(e, WorkflowError):
        return JSONResponse({'error': str(e)}, status_code=400)
    logger.warning(f'workflow API: {e}', exc_info=True)
    return JSONResponse({'error': str(e)[:300]}, status_code=500)


async def _definition_from(request: Request):
    ctype = request.headers.get('content-type', '')
    if 'yaml' in ctype:
        return (await request.body()).decode('utf-8')
    data = await request.json()
    if isinstance(data, dict) and isinstance(data.get('text'), str) and 'steps' not in data:
        return data['text'], data.get('enabled')
    return data, None


def _get_visible(svc, name: str, auth: AuthContext):
    wf = svc.store.get_workflow(name)
    if not wf or not svc.can_manage(wf, auth.user_id, auth.is_admin):
        raise KeyError(name)
    return wf


@router.get('/api/workflows')
async def api_list(auth: AuthContext = Depends(require_auth)):
    svc = _svc()
    if svc is None:
        return _unavailable()
    try:
        rows = await run_in_threadpool(svc.visible, auth.user_id, auth.is_admin)
    except Exception as e:
        return _error(e)
    return JSONResponse({'workflows': [_wf_public(w) for w in rows], 'status': svc.status()})


@router.post('/api/workflows/validate')
async def api_validate(request: Request, auth: AuthContext = Depends(require_auth)):
    svc = _svc()
    if svc is None:
        return _unavailable()
    try:
        got = await _definition_from(request)
        raw = got[0] if isinstance(got, tuple) else got
        defn = svc.validate(raw)
    except Exception as e:
        return _error(e)
    from sajha.workflows.model import public, to_yaml, topo_order
    return JSONResponse({'valid': True, 'definition': public(defn), 'yaml': to_yaml(public(defn)),
                         'order': topo_order(defn['steps'])})


@router.post('/api/workflows')
async def api_save(request: Request, auth: AuthContext = Depends(require_auth)):
    svc = _svc()
    if svc is None:
        return _unavailable()
    try:
        got = await _definition_from(request)
        raw, enabled = got if isinstance(got, tuple) else (got, None)
        wf = await run_in_threadpool(svc.save, raw, auth.user_id, auth.is_admin, enabled)
    except Exception as e:
        return _error(e)
    return JSONResponse({'success': True, 'workflow': _wf_public(wf)})


@router.get('/api/workflows/runs/{run_id}')
async def api_run(run_id: str, auth: AuthContext = Depends(require_auth)):
    svc = _svc()
    if svc is None:
        return _unavailable()
    run = await run_in_threadpool(svc.run_detail, run_id)
    if not run:
        return JSONResponse({'error': 'not found'}, status_code=404)
    wf = svc.store.get_workflow(run['workflow'])
    if not auth.is_admin and run['run_as'] != auth.user_id and not (wf and wf['owner'] == auth.user_id):
        return JSONResponse({'error': 'not found'}, status_code=404)
    return JSONResponse({'run': _run_public(run, full=True)})


@router.post('/api/workflows/runs/{run_id}/cancel')
async def api_cancel(run_id: str, auth: AuthContext = Depends(require_auth)):
    svc = _svc()
    if svc is None:
        return _unavailable()
    try:
        run = await run_in_threadpool(svc.cancel, run_id, auth.user_id, auth.is_admin)
    except Exception as e:
        return _error(e)
    return JSONResponse({'run': _run_public(run)})


@router.post('/api/workflows/runs/{run_id}/rerun')
async def api_rerun(run_id: str, request: Request, auth: AuthContext = Depends(require_auth)):
    svc = _svc()
    if svc is None:
        return _unavailable()
    try:
        body = await request.json() if (await request.body()) else {}
    except ValueError:
        body = {}
    try:
        run = await run_in_threadpool(svc.rerun, run_id, auth.user_id, auth.is_admin, body.get('from_step') or None,
                                      bool(body.get('latest_definition')))
    except Exception as e:
        return _error(e)
    return JSONResponse({'run': _run_public(run)}, status_code=202)


@router.get('/api/workflows/{name}')
async def api_get(name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    svc = _svc()
    if svc is None:
        return _unavailable()
    try:
        wf = _get_visible(svc, name, auth)
    except Exception as e:
        return _error(e)
    reveal = request.query_params.get('reveal') in ('1', 'true') and svc.can_manage(wf, auth.user_id, auth.is_admin)
    if request.query_params.get('format') == 'yaml':
        from sajha.workflows.model import public, to_yaml
        return PlainTextResponse(to_yaml(public(wf['definition'], reveal)), media_type='application/yaml')
    return JSONResponse(_wf_public(wf, reveal))


@router.put('/api/workflows/{name}')
async def api_put(name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    svc = _svc()
    if svc is None:
        return _unavailable()
    try:
        got = await _definition_from(request)
        raw, enabled = got if isinstance(got, tuple) else (got, None)
        if isinstance(raw, str):
            raw = svc.validate(raw)
        if raw.get('name') not in (None, name):
            return JSONResponse({'error': 'the name in the body differs from the URL'}, status_code=400)
        raw['name'] = name
        if not svc.store.get_workflow(name):
            raise KeyError(name)
        wf = await run_in_threadpool(svc.save, raw, auth.user_id, auth.is_admin, enabled)
    except Exception as e:
        return _error(e)
    return JSONResponse({'success': True, 'workflow': _wf_public(wf)})


@router.delete('/api/workflows/{name}')
async def api_delete(name: str, auth: AuthContext = Depends(require_auth)):
    svc = _svc()
    if svc is None:
        return _unavailable()
    try:
        ok = await run_in_threadpool(svc.delete, name, auth.user_id, auth.is_admin)
    except Exception as e:
        return _error(e)
    return JSONResponse({'success': True} if ok else {'error': 'not found'}, status_code=200 if ok else 404)


@router.post('/api/workflows/{name}/enable')
@router.post('/api/workflows/{name}/disable')
async def api_enable(name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    svc = _svc()
    if svc is None:
        return _unavailable()
    enabled = request.url.path.endswith('/enable')
    try:
        wf = await run_in_threadpool(svc.set_enabled, name, enabled, auth.user_id, auth.is_admin)
    except Exception as e:
        return _error(e)
    return JSONResponse({'success': True, 'workflow': _wf_public(wf)})


@router.post('/api/workflows/{name}/runs')
async def api_start(name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    svc = _svc()
    if svc is None:
        return _unavailable()
    try:
        body = await request.json() if (await request.body()) else {}
    except ValueError:
        return JSONResponse({'error': 'the body is JSON: {"input": {...}}'}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({'error': 'the body is a JSON object'}, status_code=400)
    try:
        _get_visible(svc, name, auth)
        key = request.headers.get('Idempotency-Key') or body.get('idempotency_key') or None
        run = await run_in_threadpool(lambda: svc.start_run(
            name, body.get('input') or {}, trigger_type='manual', trigger_id='api', started_by=auth.user_id,
            idempotency_key=f'manual:{key}' if key else None))
        wait = float(body.get('wait') or request.query_params.get('wait') or 0)
        if wait > 0:
            run = await run_in_threadpool(svc.wait_for, run['id'], min(wait, 300.0))
    except Exception as e:
        return _error(e)
    done = run['status'] in ('succeeded', 'failed', 'cancelled')
    return JSONResponse({'run': _run_public(run)}, status_code=200 if done else 202)


@router.get('/api/workflows/{name}/runs')
async def api_runs(name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    svc = _svc()
    if svc is None:
        return _unavailable()
    try:
        _get_visible(svc, name, auth)
        limit = int(request.query_params.get('limit') or 50)
        runs = await run_in_threadpool(svc.store.list_runs, name, request.query_params.get('status') or None, limit)
    except Exception as e:
        return _error(e)
    return JSONResponse({'runs': [_run_public(r) for r in runs]})


@router.post('/api/workflows/{name}/hooks/{trigger_id}')
async def api_webhook(name: str, trigger_id: str, request: Request):
    """Inbound webhook: no session; the HMAC signature over timestamp and body authenticates it."""
    svc = _svc()
    if svc is None:
        return _unavailable()
    body = await request.body()
    if len(body) > 1024 * 1024:
        return JSONResponse({'error': 'body too large (1 MiB)'}, status_code=413)
    status, payload = await run_in_threadpool(svc.receive_webhook, name, trigger_id, body, dict(request.headers))
    return JSONResponse(payload, status_code=status)


# ── the page ─────────────────────────────────────────────────────

@router.get('/workflows', name='workflows_page')
async def workflows_page(request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import render, tools_registry
    tool_names = sorted(tools_registry.tools.keys()) if tools_registry else []
    svc = _svc()
    return render(request, 'workflows/workflows.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'tool_names': tool_names,
        'available': svc is not None and svc.enabled,
        'state_shared': bool(svc and svc.status().get('state_shared')),
    })
