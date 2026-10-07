"""
SAJHA MCP Server — Data Connectors admin: the page and its JSON API (admin only).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

  GET    /admin/connectors                     the page
  GET    /api/connectors                       connections, their tools and state
  GET    /api/connectors/kinds                 each kind, its package, whether it is installed
  POST   /api/connectors                       create or replace a connection; syncs its tools
  POST   /api/connectors/test                  test an unsaved definition
  POST   /api/connectors/sync                  regenerate every connection's tools
  POST   /api/connectors/view-preview          the input schema a view would get
  GET    /api/connectors/{id}                  one connection's record
  DELETE /api/connectors/{id}                  remove it and its tools
  POST   /api/connectors/{id}/refresh          refresh its catalog
  GET    /api/connectors/{id}/tables           its catalog
  GET    /api/connectors/{id}/describe?table=  one table (or collection)

Every change is audited. Design: docs/architecture/Data Connectors.md.
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
router = APIRouter(tags=['connectors'])


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
        AuditLogger().config_changed(f'connectors.{what}', by_user=auth.user_id,
                                     details=json.dumps(details, default=str)[:2000] if details else None)
    except Exception as e:
        logger.debug(f'connectors audit: {e}')


async def _run(fn, *args, **kwargs) -> JSONResponse:
    from sajha.connectors.drivers import ConnectorError, DriverMissing
    from sajha.connectors.guard import GuardError
    from sajha.connectors.service import ConnectorServiceError
    try:
        result = await run_in_threadpool(fn, *args, **kwargs)
    except (ConnectorServiceError, GuardError) as e:
        return _fail(str(e))
    except (ConnectorError, DriverMissing) as e:
        return _fail(str(e), 502)
    except Exception as e:
        logger.error(f'data connectors: {e}', exc_info=True)
        return _fail(f'{e.__class__.__name__}: {e}', 500)
    return JSONResponse(result if isinstance(result, dict) else {'success': True, 'items': result})


# ── page ────────────────────────────────────────────────────────────

@router.get('/admin/connectors')
async def admin_connectors_page(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.connectors import guard, settings
    from sajha.connectors.model import MASK_MODES, VIEW_OPERATORS
    return render(request, 'admin/connectors.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': True,
        'enabled': settings.enabled(),
        'sqlglot': guard.sqlglot_available(),
        'mask_modes': MASK_MODES,
        'view_operators': VIEW_OPERATORS,
        'defaults': {'max_rows': settings.default_max_rows(), 'max_bytes': settings.default_max_bytes(),
                     'timeout_seconds': settings.default_timeout_seconds()},
    })


# ── API ─────────────────────────────────────────────────────────────

@router.get('/api/connectors')
async def connectors_list(auth: AuthContext = Depends(require_admin)):
    from sajha.connectors import service
    return await _run(lambda: {'success': True, 'connections': service.list_connections(_registry())})


@router.get('/api/connectors/kinds')
async def connectors_kinds(auth: AuthContext = Depends(require_admin)):
    from sajha.connectors import service
    return await _run(lambda: {'success': True, 'kinds': service.kinds()})


@router.post('/api/connectors')
async def connectors_save(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.connectors import service
    data = await _body(request)
    create = bool(data.pop('create', False))
    response = await _run(service.save, data, _registry(), auth.user_id, create)
    try:
        result = json.loads(response.body)
    except ValueError:
        result = {}
    _audit(auth, 'save', {'id': data.get('id'), 'kind': data.get('kind'),
                          **{k: result.get(k) for k in ('added', 'updated', 'removed', 'failed', 'error')}})
    return response


@router.post('/api/connectors/test')
async def connectors_test(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.connectors import service
    data = await _body(request)
    _audit(auth, 'test', {'id': data.get('id'), 'kind': data.get('kind')})
    return await _run(service.test, data)


@router.post('/api/connectors/sync')
async def connectors_sync(auth: AuthContext = Depends(require_admin)):
    from sajha.connectors import service
    _audit(auth, 'sync')
    return await _run(service.sync_all, _registry())


@router.post('/api/connectors/view-preview')
async def connectors_view_preview(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.connectors import service
    return await _run(service.view_schema_preview, await _body(request))


@router.get('/api/connectors/{cid}')
async def connectors_get(cid: str, auth: AuthContext = Depends(require_admin)):
    from sajha.connectors import service
    return await _run(lambda: {'success': True, 'connection': service.get(cid)})


@router.delete('/api/connectors/{cid}')
async def connectors_delete(cid: str, auth: AuthContext = Depends(require_admin)):
    from sajha.connectors import service
    response = await _run(service.delete, cid, _registry())
    _audit(auth, 'delete', {'id': cid, 'status': response.status_code})
    return response


@router.post('/api/connectors/{cid}/refresh')
async def connectors_refresh(cid: str, auth: AuthContext = Depends(require_admin)):
    from sajha.connectors import service
    return await _run(service.refresh, cid)


@router.get('/api/connectors/{cid}/tables')
async def connectors_tables(cid: str, auth: AuthContext = Depends(require_admin)):
    from sajha.connectors import service
    return await _run(service.tables, cid)


@router.get('/api/connectors/{cid}/describe')
async def connectors_describe(cid: str, table: str = '', auth: AuthContext = Depends(require_admin)):
    from sajha.connectors import service
    return await _run(service.describe, cid, table)
