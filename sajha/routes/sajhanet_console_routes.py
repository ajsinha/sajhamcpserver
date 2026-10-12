"""
SAJHA MCP Server — the SAJHA Net console's management pages and their JSON (design §17.1), for administrators:

* ``/admin/sajhanet/reviews`` (conflicts and reviews), ``/users`` (users across the net), ``/blocks`` (access
  and blocks), ``/keys`` (the key directory), ``/snapshots``, ``/activity`` (live activity), ``/certificates``,
  ``/settings`` (net settings), ``/sponsored`` (sponsored MCP servers) and ``/changes`` (the change history
  with undo).
* ``/api/sajhanet/...``: the views behind them, the blast radius of a change before it is made, the change
  history and undo, and the snapshot actions (compare, download, restore).

Every change goes through ``sajha.net.integration.changes`` (reason, history, undo, audit). A change from a
console session carries the page's CSRF token (``X-CSRF-Token``); a caller that arrived through the net is
refused (net settings change only at this server's own console). Included by ``sajhanet_routes.py``.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

from sajha.app import render
from sajha.auth import AuthContext, require_admin

router = APIRouter(tags=['sajhanet'])


def _user(auth: AuthContext) -> Dict[str, Any]:
    return {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles}


def csrf_for(request: Request, auth: AuthContext) -> str:
    from sajha.routes.policy_routes import csrf_token
    return csrf_token(request, auth)


def csrf_refusal(request: Request, auth: AuthContext):
    """None when the request may change something; else the 403 to answer (a console session without
    the page's token). API keys and bearer tokens carry no cookie and need none."""
    from sajha.routes.policy_routes import _csrf_ok
    if _csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
        return None
    return JSONResponse({'error': 'missing or invalid X-CSRF-Token (reload the page)'}, status_code=403)


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def _json(fn, *args, **kw):
    from sajha.routes.sajhanet_routes import _err
    try:
        return JSONResponse(await run_in_threadpool(fn, *args, **kw))
    except Exception as e:
        return _err(e)


def _page(request: Request, auth: AuthContext, template: str, view: Dict[str, Any], **extra):
    return render(request, template, dict({'user': _user(auth), 'is_admin': True, 'view': view,
                                           'csrf': csrf_for(request, auth)}, **extra))


def _off() -> JSONResponse:
    return JSONResponse({'error': 'SAJHA Net is off (sajhanet.enabled: false)'}, status_code=503)


def _running() -> bool:
    from sajha.net.integration import get_service
    svc = get_service()
    return svc is not None and svc.shared.enabled


# ── the pages ───────────────────────────────────────────────────────

@router.get('/admin/sajhanet/reviews')
async def admin_sajhanet_reviews_page(request: Request, net: str = '', auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import reviews_view
    return _page(request, auth, 'admin/sajhanet_reviews.html', await run_in_threadpool(reviews_view, net or None))


@router.get('/admin/sajhanet/users')
async def admin_sajhanet_users_page(request: Request, net: str = '', auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import users_page
    return _page(request, auth, 'admin/sajhanet_users.html', await run_in_threadpool(users_page, net or None))


@router.get('/admin/sajhanet/blocks')
async def admin_sajhanet_blocks_page(request: Request, net: str = '', auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import blocks_page
    return _page(request, auth, 'admin/sajhanet_blocks.html', await run_in_threadpool(blocks_page, net or None))


@router.get('/admin/sajhanet/keys')
async def admin_sajhanet_keys_page(request: Request, net: str = '', home: str = '',
                                   auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import keys_page
    return _page(request, auth, 'admin/sajhanet_keys.html', await run_in_threadpool(keys_page, net or None, home))


@router.get('/admin/sajhanet/snapshots')
async def admin_sajhanet_snapshots_page(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import snapshots_view
    return _page(request, auth, 'admin/sajhanet_snapshots.html', await run_in_threadpool(snapshots_view))


@router.get('/admin/sajhanet/activity')
async def admin_sajhanet_activity_page(request: Request, net: str = '', trace: str = '',
                                       auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import activity_view, trace_view
    view = await run_in_threadpool(activity_view, net or None)
    tv = await run_in_threadpool(trace_view, trace) if trace else None
    return _page(request, auth, 'admin/sajhanet_activity.html', view, trace=tv)


@router.get('/admin/sajhanet/certificates')
async def admin_sajhanet_certificates_page(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import certificates_view
    return _page(request, auth, 'admin/sajhanet_certificates.html', await run_in_threadpool(certificates_view))


@router.get('/admin/sajhanet/settings')
async def admin_sajhanet_settings_page(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import settings_view
    return _page(request, auth, 'admin/sajhanet_settings.html', await run_in_threadpool(settings_view))


@router.get('/admin/sajhanet/sponsored')
async def admin_sajhanet_sponsored_page(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import sponsored_view
    return _page(request, auth, 'admin/sajhanet_sponsored.html', await run_in_threadpool(sponsored_view))


@router.get('/admin/sajhanet/changes')
async def admin_sajhanet_changes_page(request: Request, net: str = '', auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.changes import history
    from sajha.net.integration.pages import _base
    view = _base(net or None)
    view['changes'] = await run_in_threadpool(history, view['net'], None, 200) if view.get('net') else []
    return _page(request, auth, 'admin/sajhanet_changes.html', view)


# ── the views as JSON ───────────────────────────────────────────────

@router.get('/api/sajhanet/reviews')
async def sajhanet_reviews(net: str = '', auth: AuthContext = Depends(require_admin)):
    """The conflicts and reviews queue of one net (``?net=``)."""
    from sajha.net.integration.pages import reviews_view
    return await _json(reviews_view, net or None)


@router.get('/api/sajhanet/nets/{net}/users/by-instance')
async def sajhanet_users_by_instance(net: str, auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import users_page
    return await _json(users_page, net)


@router.get('/api/sajhanet/nets/{net}/access-matrix')
async def sajhanet_access_matrix(net: str, auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import blocks_page
    return await _json(blocks_page, net)


@router.get('/api/sajhanet/nets/{net}/instances/{instance}/detail')
async def sajhanet_instance_detail(net: str, instance: str, auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import instance_admin
    return await _json(instance_admin, net, instance)


@router.get('/api/sajhanet/activity')
async def sajhanet_activity(net: str = '', instance: str = '', user: str = '', tool: str = '', outcome: str = '',
                            since: str = '', limit: int = 100, auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import activity_view
    return await _json(activity_view, net or None, instance, user, tool, outcome, since, limit)


@router.get('/api/sajhanet/activity/trace/{trace_id}')
async def sajhanet_trace(trace_id: str, auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import trace_view
    return await _json(trace_view, trace_id)


@router.get('/api/sajhanet/certificates')
async def sajhanet_certificates(auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import certificates_view
    return await _json(certificates_view)


@router.get('/api/sajhanet/settings')
async def sajhanet_settings(auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import settings_view
    return await _json(settings_view)


# ── changes: blast radius, history, undo ────────────────────────────

@router.get('/api/sajhanet/nets/{net}/blast-radius')
async def sajhanet_blast_radius(net: str, request: Request, kind: str = '', auth: AuthContext = Depends(require_admin)):
    """What a change would take away before it is made: ``?kind=block_add&level=instance&target_instance=x``
    (and ``tool``, ``user``, ``direction``, ``instance``, ``peer``, ``trust``, ``remote_user``)."""
    from sajha.net.integration.changes import blast_radius
    params = {k: v for k, v in request.query_params.items() if k != 'kind'}
    return await _json(blast_radius, net, kind, params)


@router.get('/api/sajhanet/nets/{net}/changes')
async def sajhanet_changes(net: str, instance: str = '', limit: int = 100, auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.changes import history
    if not _running():
        return _off()
    return await _json(lambda: {'net': net, 'changes': history(net, instance or None, limit)})


@router.post('/api/sajhanet/nets/{net}/changes/{change_id}/undo')
async def sajhanet_undo(net: str, change_id: str, request: Request, auth: AuthContext = Depends(require_admin)):
    """``{"reason"}`` (required): apply the change's inverse, as a new change."""
    bad = csrf_refusal(request, auth)
    if bad is not None:
        return bad
    if not _running():
        return _off()
    from sajha.net.integration.changes import undo
    b = await _body(request)
    return await _json(undo, net, change_id, auth.user_id, str(b.get('reason') or ''), auth.auth_type)


# ── snapshots ───────────────────────────────────────────────────────

@router.get('/api/sajhanet/snapshots')
async def sajhanet_snapshots(auth: AuthContext = Depends(require_admin)):
    """Retained snapshots with chain and signature status, and the writer's status."""
    from sajha.net.integration.pages import snapshots_view
    return await _json(snapshots_view)


@router.get('/api/sajhanet/snapshots/diff')
async def sajhanet_snapshot_diff(a: str = 'previous', b: str = 'latest', auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import snapshot_diff
    try:
        return JSONResponse(await run_in_threadpool(snapshot_diff, a, b))
    except FileNotFoundError as e:
        return JSONResponse({'error': str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({'error': f'{e.__class__.__name__}: {e}'}, status_code=400)


@router.get('/api/sajhanet/snapshots/{name}/download')
async def sajhanet_snapshot_download(name: str, auth: AuthContext = Depends(require_admin)):
    from sajha.net.integration.pages import _snap
    store = _snap().store
    try:
        n = store.resolve(name)
        path = store.path(n)
    except (FileNotFoundError, ValueError) as e:
        return JSONResponse({'error': str(e)}, status_code=404)
    from sajha.snapshots import _audit
    _audit('snapshot.downloaded', 'success', n, actor=auth.user_id)
    return FileResponse(str(path), filename=n,
                        media_type='application/gzip' if n.endswith('.gz') else 'application/json')


@router.post('/api/sajhanet/snapshots/{name}/restore')
async def sajhanet_snapshot_restore(name: str, request: Request, auth: AuthContext = Depends(require_admin)):
    """``{"dry_run": true}`` plans; ``{"confirm": "<the snapshot name>", "reason", "keys"?}`` restores the roles,
    users and persistent key records the snapshot holds and the database lacks (nothing existing changes)."""
    bad = csrf_refusal(request, auth)
    if bad is not None:
        return bad
    if auth.auth_type == 'sajhanet':
        return JSONResponse({'error': 'a restore is made only by an administrator signed in to this server'},
                            status_code=403)
    from sajha.net.integration.pages import snapshot_restore
    b = await _body(request)
    dry = bool(b.get('dry_run', False))
    keys = bool(b.get('keys', True))
    if not dry:
        if str(b.get('confirm') or '') != name:
            return JSONResponse({'error': 'type the snapshot name to confirm the restore'}, status_code=400)
        if not str(b.get('reason') or '').strip():
            return JSONResponse({'error': 'give a reason for the restore'}, status_code=400)
    try:
        out = await run_in_threadpool(snapshot_restore, name, keys, dry)
    except FileNotFoundError as e:
        return JSONResponse({'error': str(e)}, status_code=404)
    except Exception as e:
        from sajha.routes.sajhanet_routes import _err
        return _err(e)
    if not dry:
        from sajha.snapshots import _audit
        _audit('snapshot.restored', 'success', out['name'], actor=auth.user_id,
               details={'reason': str(b.get('reason'))[:500], 'source': 'console',
                        **{k: v for k, v in out['plan'].items() if v}})
    return JSONResponse(out)
