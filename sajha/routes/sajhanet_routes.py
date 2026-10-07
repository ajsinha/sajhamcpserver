"""
SAJHA MCP Server — SAJHA Net: the protocol endpoints, the admin API and the console page.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

* ``/sajhanet/{path}``: every SAJHA Net protocol endpoint (``/sajhanet/v1/...``) on the normal port,
  handled by the participant (sajha/net/node.py). With ``sajhanet.enabled: false``, for a net this
  server is not in, or for a browser navigation, the answer is a bare 404 (protocol §7.3, §7.7).
* ``/api/sajhanet/...``: the admin API the console and ``sajha net ...`` use: status, adding a peer
  by address, runtime seeds, the CA (init, enrollment tokens, revocation), enrollment and renewal of
  this server's certificate, manual-mode pins. Admin only; never reachable through a remote call
  (net requests carry no session or API key and are served only under ``/sajhanet/``).
* ``/api/sajhanet/nets/{net}/blocks``, ``/users``, ``/role-maps``, ``/name-matching``, ``/keys``: blocks, user
  links, role maps, name matching and the key directory (design §10, §11); changes refuse a caller that
  arrived through the net (``auth_type`` ``sajhanet``): net settings are changed only by an administrator
  signed in to this server.
* ``/admin/sajhanet``: the console page (membership, adding a peer, blocks, users and keys).
* ``/net/instances`` and ``/net/instances/{net}/{instance}`` (every signed-in user): the Instances page
  and one instance's tools (design §17.1), with ``/api/sajhanet/instances`` behind them; this server is
  always listed, as a net of one when SAJHA Net is off. ``/admin/sajhanet/tools``: the Remote tools page
  (host and tool table, held tools, conflicts).

Design: docs/architecture/SAJHA Net.md; protocol: docs/protocol/SAJHA Net Protocol.md.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from starlette.requests import ClientDisconnect

from sajha.app import render
from sajha.auth import AuthContext, require_admin, require_auth

logger = logging.getLogger(__name__)
router = APIRouter(tags=['sajhanet'])


def _svc():
    from sajha.net.integration import get_service
    return get_service()


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _err(e: Exception) -> JSONResponse:
    from sajha.net.integration import ServiceError
    if isinstance(e, ServiceError):
        return JSONResponse({'error': str(e), **{k: v for k, v in e.extra.items() if v is not None}},
                            status_code=e.status)
    logger.warning(f'SAJHA Net admin: {e}', exc_info=True)
    return JSONResponse({'error': f'{e.__class__.__name__}: {e}'}, status_code=500)


async def _call(fn, *args, **kw):
    try:
        return JSONResponse(await run_in_threadpool(fn, *args, **kw))
    except Exception as e:
        return _err(e)


def _off() -> JSONResponse:
    return JSONResponse({'error': 'SAJHA Net is off (sajhanet.enabled: false)'}, status_code=503)


# ── the protocol endpoints ──────────────────────────────────────────

@router.api_route('/sajhanet/{path:path}', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'],
                  include_in_schema=False)
async def sajhanet_endpoint(request: Request, path: str):
    return await serve(_svc(), request)


async def serve(svc, request: Request) -> Response:
    """Hand one HTTP request under ``/sajhanet/`` to ``svc``'s participant (also used by tests that run
    several instances in one process)."""
    if svc is None or not svc.participant.enabled:
        return Response(status_code=404)
    try:
        body = await request.body()
    except ClientDisconnect:                 # the sender gave up (a probe past its ping timeout): nobody to answer
        return Response(status_code=400)
    proto =request.headers.get('x-forwarded-proto', '').split(',')[0].strip().lower()
    secure = request.url.scheme == 'https' or proto == 'https'
    source = request.client.host if request.client else ''
    r = await run_in_threadpool(svc.participant.handle, request.method, request.url.path, request.url.query,
                                dict(request.headers), body, secure, source)
    headers = {k: v for k, v in r.headers.items() if k.lower() not in ('content-length',)}
    return Response(content=r.body, status_code=r.status, headers=headers)


# ── the console page ────────────────────────────────────────────────

@router.get('/admin/sajhanet')
async def admin_sajhanet_page(request: Request, auth: AuthContext = Depends(require_admin)):
    svc = _svc()
    status = await run_in_threadpool(svc.status) if svc is not None else {'enabled': False, 'nets': []}
    return render(request, 'admin/sajhanet.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': True, 'status': status})


# ── the admin API ───────────────────────────────────────────────────

@router.get('/api/sajhanet/status')
async def sajhanet_status(auth: AuthContext = Depends(require_admin)):
    svc = _svc()
    if svc is None:
        return JSONResponse({'enabled': False, 'nets': []})
    return await _call(svc.status)


@router.post('/api/sajhanet/nets/{net}/peers')
async def sajhanet_add_peer(net: str, request: Request, auth: AuthContext = Depends(require_admin)):
    """Point this server at a peer for one net (design §6.6): an ordinary signed join."""
    svc = _svc()
    if svc is None or not svc.shared.enabled:
        return _off()
    b = await _body(request)
    return await _call(svc.inject, net, str(b.get('address') or ''), bool(b.get('keep_as_seed')), auth.user_id)


@router.delete('/api/sajhanet/nets/{net}/seeds')
async def sajhanet_remove_seed(net: str, request: Request, auth: AuthContext = Depends(require_admin)):
    svc = _svc()
    if svc is None or not svc.shared.enabled:
        return _off()
    b = await _body(request)
    ok = await run_in_threadpool(svc.remove_runtime_seed, net, str(b.get('url') or ''), auth.user_id)
    return JSONResponse({'removed': ok}, status_code=200 if ok else 404)


@router.post('/api/sajhanet/nets/{net}/ca/init')
async def sajhanet_ca_init(net: str, request: Request, auth: AuthContext = Depends(require_admin)):
    svc = _svc()
    if svc is None or not svc.shared.enabled:
        return _off()
    b = await _body(request)
    return await _call(svc.ca_init, net, auth.user_id, str(b.get('alg') or 'ed25519'))


@router.get('/api/sajhanet/nets/{net}/ca')
async def sajhanet_ca_view(net: str, auth: AuthContext = Depends(require_admin)):
    svc = _svc()
    if svc is None or not svc.shared.enabled:
        return _off()
    return await _call(svc.ca_view, net)


@router.post('/api/sajhanet/nets/{net}/ca/tokens')
async def sajhanet_ca_token(net: str, request: Request, auth: AuthContext = Depends(require_admin)):
    svc = _svc()
    if svc is None or not svc.shared.enabled:
        return _off()
    b = await _body(request)
    return await _call(svc.ca_token, net, str(b.get('instance') or ''), str(b.get('host') or ''), auth.user_id)


@router.post('/api/sajhanet/nets/{net}/ca/revoke')
async def sajhanet_ca_revoke(net: str, request: Request, auth: AuthContext = Depends(require_admin)):
    svc = _svc()
    if svc is None or not svc.shared.enabled:
        return _off()
    b = await _body(request)
    return await _call(svc.ca_revoke, net, str(b.get('instance') or ''), str(b.get('serial') or ''),
                       str(b.get('reason') or ''), auth.user_id)


@router.post('/api/sajhanet/nets/{net}/enroll')
async def sajhanet_enroll(net: str, request: Request, auth: AuthContext = Depends(require_admin)):
    svc = _svc()
    if svc is None or not svc.shared.enabled:
        return _off()
    b = await _body(request)
    return await _call(svc.enroll, net, str(b.get('ca_url') or ''), str(b.get('token') or ''), auth.user_id)


@router.post('/api/sajhanet/nets/{net}/renew')
async def sajhanet_renew(net: str, auth: AuthContext = Depends(require_admin)):
    svc = _svc()
    if svc is None or not svc.shared.enabled:
        return _off()
    return await _call(svc.renew, net, auth.user_id)


@router.post('/api/sajhanet/nets/{net}/pins')
async def sajhanet_add_pin(net: str, request: Request, auth: AuthContext = Depends(require_admin)):
    svc = _svc()
    if svc is None or not svc.shared.enabled:
        return _off()
    b = await _body(request)
    return await _call(svc.add_pin, net, str(b.get('thumbprint') or ''), auth.user_id)


@router.delete('/api/sajhanet/nets/{net}/pins')
async def sajhanet_remove_pin(net: str, request: Request, auth: AuthContext = Depends(require_admin)):
    svc = _svc()
    if svc is None or not svc.shared.enabled:
        return _off()
    b = await _body(request)
    ok = await run_in_threadpool(svc.remove_pin, net, str(b.get('thumbprint') or ''), auth.user_id)
    return JSONResponse({'removed': ok}, status_code=200 if ok else 404)


# ── identity and authorization (design §10, §11): local administrators only ──

def _authz():
    svc = _svc()
    if svc is None or not svc.shared.enabled or getattr(svc, 'authz', None) is None:
        return None
    return svc.authz


@router.get('/api/sajhanet/nets/{net}/blocks')
async def sajhanet_blocks(net: str, auth: AuthContext = Depends(require_admin)):
    """This instance's blocks in the net (with expired ones flagged) and the blocks peers publish."""
    a = _authz()
    return _off() if a is None else await _call(a.blocks_view, net)


@router.post('/api/sajhanet/nets/{net}/blocks')
async def sajhanet_add_block(net: str, request: Request, auth: AuthContext = Depends(require_admin)):
    a = _authz()
    if a is None:
        return _off()
    b = await _body(request)
    return await _call(a.add_block, net, str(b.get('level') or ''), str(b.get('target_instance') or ''),
                       str(b.get('reason') or ''), auth.user_id, tool=str(b.get('tool') or ''),
                       user=str(b.get('user') or ''), direction=str(b.get('direction') or 'inbound'),
                       expires_in_minutes=b.get('expires_in_minutes'), withhold_reason=bool(b.get('withhold_reason')),
                       by_auth_type=auth.auth_type)


@router.delete('/api/sajhanet/nets/{net}/blocks/{block_id}')
async def sajhanet_remove_block(net: str, block_id: str, request: Request, auth: AuthContext = Depends(require_admin)):
    a = _authz()
    if a is None:
        return _off()
    b = await _body(request)
    try:
        ok = await run_in_threadpool(a.remove_block, net, block_id, auth.user_id, str(b.get('reason') or ''),
                                     auth.auth_type)
    except Exception as e:
        return _err(e)
    return JSONResponse({'removed': ok}, status_code=200 if ok else 404)


@router.get('/api/sajhanet/nets/{net}/users')
async def sajhanet_users(net: str, auth: AuthContext = Depends(require_admin)):
    """Remote users: links, role maps, name-matching exceptions and how recent callers resolved."""
    a = _authz()
    return _off() if a is None else await _call(a.users_view, net)


@router.post('/api/sajhanet/nets/{net}/users/links')
async def sajhanet_link_user(net: str, request: Request, auth: AuthContext = Depends(require_admin)):
    a = _authz()
    if a is None:
        return _off()
    b = await _body(request)
    return await _call(a.link_user, net, str(b.get('remote_user') or ''), str(b.get('local_user') or ''),
                       auth.user_id, by_auth_type=auth.auth_type)


@router.delete('/api/sajhanet/nets/{net}/users/links')
async def sajhanet_unlink_user(net: str, request: Request, auth: AuthContext = Depends(require_admin)):
    a = _authz()
    if a is None:
        return _off()
    b = await _body(request)
    try:
        ok = await run_in_threadpool(a.unlink_user, net, str(b.get('remote_user') or ''), auth.user_id,
                                     auth.auth_type)
    except Exception as e:
        return _err(e)
    return JSONResponse({'removed': ok}, status_code=200 if ok else 404)


@router.put('/api/sajhanet/nets/{net}/role-maps/{instance}')
async def sajhanet_role_map(net: str, instance: str, request: Request, auth: AuthContext = Depends(require_admin)):
    """Set the role map for users of ``instance`` (``*``: every instance): ``{"map": {remote: [local]}}``;
    an empty map removes it."""
    a = _authz()
    if a is None:
        return _off()
    b = await _body(request)
    return await _call(a.set_role_map, net, instance, b.get('map') if isinstance(b.get('map'), dict) else {},
                       auth.user_id, by_auth_type=auth.auth_type)


@router.put('/api/sajhanet/nets/{net}/name-matching/{instance}')
async def sajhanet_name_matching(net: str, instance: str, request: Request, auth: AuthContext = Depends(require_admin)):
    a = _authz()
    if a is None:
        return _off()
    b = await _body(request)
    return await _call(a.set_name_matching, net, instance, bool(b.get('on', True)), auth.user_id,
                       by_auth_type=auth.auth_type)


@router.get('/api/sajhanet/nets/{net}/keys')
async def sajhanet_keys(net: str, home: str = '', auth: AuthContext = Depends(require_admin)):
    """The net key directory, read-only: records per home and, with ``?home=``, that home's records."""
    a = _authz()
    return _off() if a is None else await _call(a.keys_view, net, home or None)


@router.post('/api/sajhanet/nets/{net}/keys/resync')
async def sajhanet_keys_resync(net: str, auth: AuthContext = Depends(require_admin)):
    a = _authz()
    return _off() if a is None else await _call(a.resync, net, auth.user_id)


# ── catalogs and routing (design §7, §8; stream C) ──────────────────

def _catalogs():
    svc = _svc()
    return getattr(svc, 'catalogs', None) if svc is not None and svc.shared.enabled else None


@router.get('/api/sajhanet/tools')
async def sajhanet_tools(request: Request, auth: AuthContext = Depends(require_admin)):
    """The host and tool table with each plain name's resolution order (design §8.4)."""
    c = _catalogs()
    return _off() if c is None else await _call(c.table, request.query_params.get('net') or None)


@router.get('/api/sajhanet/conflicts')
async def sajhanet_conflicts(request: Request, auth: AuthContext = Depends(require_admin)):
    """Quarantined tool names with their reports, the own conflicts document, description warnings."""
    c = _catalogs()
    return _off() if c is None else await _call(c.conflicts, request.query_params.get('net') or None)


@router.get('/api/sajhanet/catalogs')
async def sajhanet_catalogs(auth: AuthContext = Depends(require_admin)):
    c = _catalogs()
    return _off() if c is None else await _call(c.status)


@router.post('/api/sajhanet/nets/{net}/peers/{peer}/trust')
async def sajhanet_set_trust(net: str, peer: str, request: Request, auth: AuthContext = Depends(require_admin)):
    """Set a peer's trust level: ``{"trust": "auto"|"review"|"pinned", "pinned": [tool, ...]}`` (design §7.3)."""
    c = _catalogs()
    if c is None:
        return _off()
    b = await _body(request)
    pinned = b.get('pinned') if isinstance(b.get('pinned'), list) else None
    return await _call(c.set_trust, net, peer, str(b.get('trust') or ''), pinned, auth.user_id)


@router.post('/api/sajhanet/nets/{net}/peers/{peer}/tools/{tool}/approve')
async def sajhanet_approve(net: str, peer: str, tool: str, auth: AuthContext = Depends(require_admin)):
    c = _catalogs()
    return _off() if c is None else await _call(c.approve, net, peer, tool, True, auth.user_id)


@router.delete('/api/sajhanet/nets/{net}/peers/{peer}/tools/{tool}/approve')
async def sajhanet_unapprove(net: str, peer: str, tool: str, auth: AuthContext = Depends(require_admin)):
    c = _catalogs()
    return _off() if c is None else await _call(c.approve, net, peer, tool, False, auth.user_id)


# ── the Instances page (every signed-in user) and Remote tools (admin), design §17.1 ─────

def _user(auth: AuthContext) -> Dict[str, Any]:
    return {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles}


@router.get('/net/instances')
async def net_instances_page(request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.net.integration.console import instances_view
    view = await run_in_threadpool(instances_view, auth)
    return render(request, 'net/instances.html', {'user': _user(auth), 'is_admin': auth.is_admin, 'view': view})


@router.get('/net/instances/this')
async def net_this_instance_page(request: Request, auth: AuthContext = Depends(require_auth)):
    """This server's own entry in its first net (a stable address for links and checks)."""
    from sajha.net.integration.console import instance_view, instances_view
    view = await run_in_threadpool(instances_view, auth)
    n = view['nets'][0] if view['nets'] else None
    one = await run_in_threadpool(instance_view, n['net'], n['instances'][0]['name'], auth) if n else None
    if one is None:
        return render(request, 'common/error.html', {'error': 'Instance not found',
                                                     'message': 'This server is in no net'}, status_code=404)
    return render(request, 'net/instance.html', {'user': _user(auth), 'is_admin': auth.is_admin, 'view': one})


@router.get('/net/instances/{net}/{instance}')
async def net_instance_page(net: str, instance: str, request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.net.integration.console import instance_view
    view = await run_in_threadpool(instance_view, net, instance, auth)
    if view is None:
        return render(request, 'common/error.html', {
            'error': 'Instance not found', 'message': f'{instance} is not a member of {net} that this server knows'},
            status_code=404)
    return render(request, 'net/instance.html', {'user': _user(auth), 'is_admin': auth.is_admin, 'view': view})


@router.get('/api/sajhanet/instances')
async def sajhanet_instances(auth: AuthContext = Depends(require_auth)):
    """Every participant of every net, this server first, with the tools this caller may use here."""
    from sajha.net.integration.console import instances_view
    return await _call(instances_view, auth)


@router.get('/api/sajhanet/instances/{net}/{instance}')
async def sajhanet_instance(net: str, instance: str, auth: AuthContext = Depends(require_auth)):
    from sajha.net.integration.console import instance_view
    view = await run_in_threadpool(instance_view, net, instance, auth)
    if view is None:
        return JSONResponse({'error': f'{instance} is not a known member of {net}'}, status_code=404)
    return JSONResponse(view)


@router.get('/admin/sajhanet/tools')
async def admin_sajhanet_tools_page(request: Request, auth: AuthContext = Depends(require_admin)):
    c = _catalogs()
    table = await run_in_threadpool(c.table) if c is not None else {'rows': [], 'resolution': {}, 'aliases': {}}
    conflicts = await run_in_threadpool(c.conflicts) if c is not None else {'nets': {}}
    from sajha.net.integration.console import _rfc
    for r in table.get('rows') or []:
        r['last_seen'] = _rfc(r.get('last_seen'))
    return render(request, 'admin/sajhanet_tools.html', {
        'user': _user(auth), 'is_admin': True, 'enabled': c is not None, 'table': table, 'conflicts': conflicts})
