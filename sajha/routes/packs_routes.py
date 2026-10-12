"""
SAJHA MCP Server — provider packs: the admin API (administrators).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

  GET  /api/admin/packs                     every pack, its licence and whether it is installed
  GET  /api/admin/packs/{id}                one pack: manifest summary, provider preset, licence text
  POST /api/admin/packs/{id}/plan           {client_id?, client_secret_ref?, tenant?} -> the plan and its hash
  POST /api/admin/packs/{id}/install        {..inputs, hash, approve: true} -> provider preset + tools
  POST /api/admin/packs/{id}/uninstall      remove the pack's tools and the preset it created

Session callers send the CSRF token in ``X-CSRF-Token`` on POST (API keys and bearer tokens need none).
The gate is the one of Describe a tool (sajha/packs/service.py). Design: docs/architecture/Connected Accounts.md §11
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from sajha.auth import AuthContext, require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/admin/packs', tags=['packs'])


def _registry():
    from sajha.app import tools_registry
    return tools_registry


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _csrf(request: Request, auth: AuthContext):
    from sajha.routes.policy_routes import _csrf_ok
    if not _csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
        return JSONResponse({'success': False, 'error': 'missing or invalid CSRF token (X-CSRF-Token)'},
                            status_code=403)
    return None


async def _run(fn, *args, **kwargs) -> JSONResponse:
    from sajha.federation.security import redact
    from sajha.packs.manifest import PackError
    try:
        result = await run_in_threadpool(fn, *args, **kwargs)
    except PackError as e:
        body = {'success': False, 'error': redact(str(e))}
        body.update({k: v for k, v in e.extra.items() if k in ('hash', 'approval_id', 'rule', 'plan')})
        return JSONResponse(body, status_code=e.status)
    except Exception as e:
        logger.error(f'packs: {e}', exc_info=True)
        return JSONResponse({'success': False, 'error': redact(f'{e.__class__.__name__}: {e}')}, status_code=500)
    return JSONResponse(result)


@router.get('')
async def packs_list(auth: AuthContext = Depends(require_admin)):
    from sajha.packs import service
    return await _run(service.catalog)


@router.get('/{pack_id}')
async def packs_show(pack_id: str, auth: AuthContext = Depends(require_admin)):
    from sajha.packs import service
    return await _run(service.show, pack_id)


@router.post('/{pack_id}/plan')
async def packs_plan(pack_id: str, request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.packs import service
    refused = _csrf(request, auth)
    if refused:
        return refused
    return await _run(service.plan, pack_id, await _body(request), _registry(), auth)


@router.post('/{pack_id}/install')
async def packs_install(pack_id: str, request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.packs import service
    refused = _csrf(request, auth)
    if refused:
        return refused
    data = await _body(request)
    return await _run(service.install, pack_id, data, str(data.get('hash') or ''), data.get('approve') is True,
                      _registry(), auth)


@router.post('/{pack_id}/uninstall')
async def packs_uninstall(pack_id: str, request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.packs import service
    refused = _csrf(request, auth)
    if refused:
        return refused
    return await _run(service.uninstall, pack_id, _registry(), auth)
