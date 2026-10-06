"""
SAJHA MCP Server — Studio "Import an API": the page and its JSON endpoints (admin only).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

  GET  /studio/api-import                     the page
  POST /admin/studio/api-import/parse         preview: operations, flags, diff against the last import
  POST /admin/studio/api-import/test          call one operation once, without deploying it
  POST /admin/studio/api-import/deploy        write + hot-load the selected tools, remove the chosen ones
  GET  /api/studio/api-import/apis            the imports made so far
  GET  /api/studio/api-import/apis/{id}       an import's saved settings (to re-import)
  POST /admin/studio/api-import/delete        remove an import and all its tools

Every change is audited. Design: docs/architecture/API Import.md.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from sajha.app import render
from sajha.auth import AuthContext, require_admin

logger = logging.getLogger(__name__)

pages = APIRouter(prefix='/studio', tags=['studio'])
actions = APIRouter(prefix='/admin/studio/api-import', tags=['studio'])
reads = APIRouter(prefix='/api/studio/api-import', tags=['studio'])


def _registry():
    from sajha.app import tools_registry
    return tools_registry


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _fail(message: str, status: int = 400) -> JSONResponse:
    from sajha.federation.security import redact
    return JSONResponse({'success': False, 'error': redact(message)}, status_code=status)


def _audit(auth: AuthContext, what: str, details: Any = None) -> None:
    try:
        from sajha.core.audit import AuditLogger
        AuditLogger().config_changed(f'api_import.{what}', by_user=auth.user_id,
                                     details=json.dumps(details, default=str)[:2000] if details else None)
    except Exception as e:
        logger.debug(f'api import audit: {e}')


async def _run(fn, *args, **kwargs) -> JSONResponse:
    from sajha.api_import.service import APIImportError
    try:
        result = await run_in_threadpool(fn, *args, **kwargs)
    except APIImportError as e:
        return _fail(str(e))
    except Exception as e:
        logger.error(f'API import failed: {e}', exc_info=True)
        return _fail(f'{e.__class__.__name__}: {e}', 500)
    return JSONResponse(result if isinstance(result, dict) else {'success': True, 'items': result})


# ── page ────────────────────────────────────────────────────────────

@pages.get('/api-import')
async def studio_api_import(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.api_import import settings
    from sajha.api_import.service import connected_accounts_available
    return render(request, 'admin/studio/studio_api_import.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': True,
        'max_tools': settings.max_tools(),
        'allow_localhost': settings.allow_localhost(),
        'allow_private': settings.allow_private_networks(),
        'connected_accounts': connected_accounts_available(),
    })


# ── actions ─────────────────────────────────────────────────────────

@actions.post('/parse')
async def api_import_parse(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.api_import import service
    return await _run(service.plan, await _body(request), _registry())


@actions.post('/test')
async def api_import_test(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.api_import import service
    data = await _body(request)
    _audit(auth, 'test', {'prefix': data.get('prefix'), 'operation': data.get('operation')})
    return await _run(service.test_call, data, _registry())


@actions.post('/deploy')
async def api_import_deploy(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.api_import import service
    data = await _body(request)
    response = await _run(service.deploy, data, _registry(), auth.user_id)
    try:
        result = json.loads(response.body)
    except ValueError:
        result = {}
    _audit(auth, 'deploy', {k: result.get(k) for k in ('api_id', 'deployed', 'updated', 'removed', 'failed', 'error')})
    return response


@reads.get('/apis')
async def api_import_list(auth: AuthContext = Depends(require_admin)):
    from sajha.api_import import service
    return await _run(lambda: {'success': True, 'apis': service.list_apis(_registry())})


@reads.get('/apis/{api_id}')
async def api_import_get(api_id: str, auth: AuthContext = Depends(require_admin)):
    from sajha.api_import import service
    return await _run(lambda: {'success': True, 'request': service.reimport_request(api_id)})


@actions.post('/delete')
async def api_import_delete(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.api_import import service
    api_id = str((await _body(request)).get('api_id') or '').strip().lower()
    response = await _run(service.delete_api, api_id, _registry())
    _audit(auth, 'delete', {'api_id': api_id, 'status': response.status_code})
    return response


# (include_router copies routes, so this must stay at the end of the module.)
router = APIRouter()
router.include_router(pages)
router.include_router(actions)
router.include_router(reads)
