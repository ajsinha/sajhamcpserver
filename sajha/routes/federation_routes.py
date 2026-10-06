"""
SAJHA MCP Server — Federation admin: the page and its JSON API (admin only).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

/admin/federation lists the upstream MCP servers SAJHA fronts, their state and what they
offer; administrators add, edit, remove, test and refresh upstreams and approve, reject,
disable or enable each discovered tool, prompt and resource. Every change is audited.
Design: docs/architecture/Federation.md.
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
router = APIRouter(tags=['federation'])


def _manager():
    from sajha.federation.manager import get_federation
    return get_federation()


def _audit(auth: AuthContext, what: str, details: Any = None) -> None:
    try:
        from sajha.core.audit import AuditLogger
        AuditLogger().config_changed(f'federation.{what}', by_user=auth.user_id,
                                     details=json.dumps(details, default=str)[:2000] if details else None)
    except Exception as e:
        logger.debug(f'federation audit: {e}')


def _error(status: int, message: str) -> JSONResponse:
    from sajha.federation.security import redact
    return JSONResponse({'error': redact(message)}, status_code=status)


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _off() -> JSONResponse:
    return _error(503, 'federation is not initialised')


# ── page ────────────────────────────────────────────────────────────

@router.get('/admin/federation')
async def admin_federation_page(request: Request, auth: AuthContext = Depends(require_admin)):
    m = _manager()
    return render(request, 'admin/federation.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': True,
        'summary': m.summary() if m else {'enabled': False, 'upstreams': 0, 'exposed_tools': 0,
                                          'require_approval': True, 'allow_stdio': False, 'config_errors': {}},
    })


# ── API ─────────────────────────────────────────────────────────────

@router.get('/api/federation/upstreams')
async def federation_upstreams(auth: AuthContext = Depends(require_admin)):
    m = _manager()
    if m is None:
        return {'summary': {'enabled': False}, 'upstreams': []}
    return {'summary': m.summary(), 'upstreams': await run_in_threadpool(m.status)}


@router.get('/api/federation/upstreams/{upstream_id}')
async def federation_upstream(upstream_id: str, auth: AuthContext = Depends(require_admin)):
    m = _manager()
    if m is None:
        return _off()
    try:
        return await run_in_threadpool(m.status, upstream_id)
    except KeyError:
        return _error(404, f'no upstream {upstream_id}')


@router.post('/api/federation/upstreams')
async def federation_add(request: Request, auth: AuthContext = Depends(require_admin)):
    m = _manager()
    if m is None:
        return _off()
    data = await _body(request)
    try:
        cfg = await run_in_threadpool(m.add_upstream, data)
    except (ValueError, KeyError) as e:
        return _error(400, str(e))
    _audit(auth, 'upstream_add', cfg.to_dict())
    return JSONResponse({'ok': True, 'upstream': cfg.to_dict()}, status_code=201)


@router.put('/api/federation/upstreams/{upstream_id}')
async def federation_edit(upstream_id: str, request: Request, auth: AuthContext = Depends(require_admin)):
    m = _manager()
    if m is None:
        return _off()
    data = await _body(request)
    data['id'] = upstream_id
    try:
        cfg = await run_in_threadpool(lambda: m.add_upstream(data, replace=True))
    except KeyError:
        return _error(404, f'no upstream {upstream_id}')
    except ValueError as e:
        return _error(400, str(e))
    _audit(auth, 'upstream_edit', cfg.to_dict())
    return {'ok': True, 'upstream': cfg.to_dict()}


@router.delete('/api/federation/upstreams/{upstream_id}')
async def federation_remove(upstream_id: str, auth: AuthContext = Depends(require_admin)):
    m = _manager()
    if m is None:
        return _off()
    try:
        removed = await run_in_threadpool(m.remove_upstream, upstream_id)
    except ValueError as e:
        return _error(400, str(e))
    if not removed:
        return _error(404, f'no upstream {upstream_id}')
    _audit(auth, 'upstream_remove', {'id': upstream_id})
    return {'ok': True}


@router.post('/api/federation/upstreams/{upstream_id}/refresh')
async def federation_refresh(upstream_id: str, auth: AuthContext = Depends(require_admin)):
    m = _manager()
    if m is None:
        return _off()
    try:
        status = await run_in_threadpool(m.refresh, upstream_id)
    except KeyError:
        return _error(404, f'no upstream {upstream_id}')
    except Exception as e:
        return _error(502, f'refresh failed: {e}')
    return {'ok': True, 'upstream': status}


@router.post('/api/federation/upstreams/{upstream_id}/items')
async def federation_item(upstream_id: str, request: Request, auth: AuthContext = Depends(require_admin)):
    m = _manager()
    if m is None:
        return _off()
    data = await _body(request)
    kind, name, action = data.get('kind') or 'tool', data.get('name') or '', data.get('action') or ''
    try:
        n = await run_in_threadpool(m.set_item_status, upstream_id, kind, name, action)
    except KeyError as e:
        return _error(404, f'not found: {e}')
    except ValueError as e:
        return _error(400, str(e))
    _audit(auth, f'item_{action}', {'upstream': upstream_id, 'kind': kind, 'name': name, 'changed': n})
    return {'ok': True, 'changed': n}


@router.post('/api/federation/test')
async def federation_test(request: Request, auth: AuthContext = Depends(require_admin)):
    m = _manager()
    if m is None:
        return _off()
    data = await _body(request)
    if not data.get('id'):
        data['id'] = 'test'
    try:
        result = await run_in_threadpool(m.test_connection, data)
    except ValueError as e:
        return _error(400, str(e))
    except Exception as e:
        return _error(502, f'test failed: {e}')
    return result
