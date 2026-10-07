"""
System notices over HTTP (docs/architecture/System Notices.md).

    GET  /api/notices                              the caller's view: banner, badge, open notices
    GET  /api/notices/stream                       the same view as server-sent events, on every change
    GET  /api/admin/notices                        every notice (?state=open|cleared|all, ?source=)
    POST /api/admin/notices/{id}/acknowledge       stop the banner shouting (admin; CSRF for the console)
    POST /api/admin/notices/{id}/clear             clear now (a source still in its condition raises it again)

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from sajha import notices as N
from sajha.auth import AuthContext, require_admin, require_auth
from sajha.routes.policy_routes import _cookie_auth, _csrf_ok, csrf_token

router = APIRouter(tags=['notices'])

STREAM_POLL_SECONDS = 2.0


def _view(request: Request, auth: AuthContext, include_cleared: bool = False) -> dict:
    out = N.view(auth.is_admin, authenticated=True, include_cleared=include_cleared)
    if auth.is_admin and _cookie_auth(request):
        out['csrf'] = csrf_token(request, auth)
    return out


@router.get('/api/notices')
async def notices_view(request: Request, cleared: bool = False, auth: AuthContext = Depends(require_auth)):
    return _view(request, auth, include_cleared=cleared)


@router.get('/api/notices/stream')
async def notices_stream(request: Request, cleared: bool = False, once: bool = False,
                         auth: AuthContext = Depends(require_auth)):
    """``event: notices`` with the caller's view now and after every change (``once=1``: one event)."""
    from sse_starlette.sse import EventSourceResponse
    svc = N.get_service()

    async def events():
        last = None
        sweep_every, ticks = 15, 0
        while True:
            ticks += 1
            if ticks % sweep_every == 0:
                await asyncio.to_thread(svc.sweep)
            v = await asyncio.to_thread(svc.version)
            if v != last:
                last = v
                data = await asyncio.to_thread(_view, request, auth, cleared)
                yield {'event': 'notices', 'id': str(v), 'data': json.dumps(data, default=str)}
                if once:
                    return
            if await request.is_disconnected():
                return
            await asyncio.sleep(STREAM_POLL_SECONDS)

    return EventSourceResponse(events(), ping=15, headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


@router.get('/api/admin/notices')
async def admin_notices(state: str = 'open', source: str = '', auth: AuthContext = Depends(require_admin)):
    if state not in ('open', 'cleared', 'all'):
        return JSONResponse({'error': 'state must be open, cleared or all'}, 400)
    return {'enabled': N.enabled(),
            'notices': [N.public(n, admin=True) for n in N.list_notices(state, source or None)]}


def _csrf(request: Request, auth: AuthContext):
    if not _csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
        return JSONResponse({'error': 'missing or invalid X-CSRF-Token'}, 403)
    return None


@router.post('/api/admin/notices/{notice_id:path}/acknowledge')
async def admin_notice_acknowledge(notice_id: str, request: Request, auth: AuthContext = Depends(require_admin)):
    bad = _csrf(request, auth)
    if bad:
        return bad
    n = N.acknowledge_notice(notice_id, auth.user_id or auth.user_name or 'admin')
    if n is None:
        return JSONResponse({'error': f'no notice {notice_id!r}'}, 404)
    return {'notice': N.public(n, admin=True)}


@router.post('/api/admin/notices/{notice_id:path}/clear')
async def admin_notice_clear(notice_id: str, request: Request, auth: AuthContext = Depends(require_admin)):
    bad = _csrf(request, auth)
    if bad:
        return bad
    svc = N.get_service()
    if svc.get(notice_id) is None:
        return JSONResponse({'error': f'no notice {notice_id!r}'}, 404)
    svc.clear(notice_id, reason='admin', by=auth.user_id or auth.user_name or 'admin')
    return {'notice': N.public(svc.get(notice_id) or {'id': notice_id}, admin=True)}
