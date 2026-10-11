"""
SAJHA MCP Server — Server connections: each user's own sign-in to proxied MCP servers.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

A proxied server with ``auth.type: token_user`` is called as the person who asked, with a
personal token that person saves here once (sajha/federation/user_tokens.py).

    GET    /account/server-connections                       your connections to proxied servers
    GET    /account/server-connections/{upstream}            the connect page: add, replace, remove
    POST   /account/server-connections/{upstream}/token      save a token (CSRF; tested first)
    POST   /account/server-connections/{upstream}/remove     forget your token (CSRF)
    GET    /admin/server-connections                         who is connected to which server; revoke
    POST   /admin/server-connections/revoke                  an administrator removes a user's token (CSRF)
    GET    /api/accounts/server-connections                  JSON: your connections
    PUT    /api/accounts/server-connections/{upstream}       JSON {"token", "test"}: save (X-CSRF-Token with a cookie)
    DELETE /api/accounts/server-connections/{upstream}       JSON: remove (X-CSRF-Token with a cookie)
    GET    /api/admin/server-connections                     JSON: every connection (admin; never a token)
    DELETE /api/admin/server-connections/{upstream}/{user}   JSON: revoke one (admin)

No page or API ever returns a saved token: status shows a masked hint only.
Design: docs/architecture/Per-User Sign-In for Proxied Servers.md
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from sajha.app import render
from sajha.auth import AuthContext, require_admin, require_auth
from sajha.routes.accounts_routes import _csrf_ok, _ip, _user, csrf_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=['server-connections'])


def _manager():
    from sajha.federation.manager import get_federation
    return get_federation()


def _tokens():
    from sajha.federation.user_tokens import get_tokens
    return get_tokens()


def _is_user(auth: AuthContext) -> bool:
    from sajha.accounts.service import is_user_caller
    return is_user_caller(auth.user_id)


def _per_user_configs() -> List[Any]:
    """Every proxied server that signs each user in (token_user, oauth_user)."""
    from sajha.federation.user_tokens import PER_USER_MODES, auth_mode
    m = _manager()
    if m is None:
        return []
    out = []
    for uid in m.upstream_ids():
        cfg = m.get_config(uid)
        if cfg is not None and auth_mode(cfg) in PER_USER_MODES:
            out.append(cfg)
    return out


def _config(upstream_id: str):
    return next((c for c in _per_user_configs() if c.id == upstream_id), None)


def _fed_state() -> Dict[str, Any]:
    m = _manager()
    return {'federation_on': bool(m is not None and m.settings.enabled)}


def _rows_for(user_id: str, wanted: str = '') -> List[Dict[str, Any]]:
    t = _tokens()
    rows = []
    for cfg in _per_user_configs():
        try:
            st = t.status_of(cfg, user_id)
        except Exception as e:
            st = {'upstream': cfg.id, 'title': cfg.display_title, 'mode': 'token_user', 'status': 'not_connected',
                  'last_error': f'the token vault is unavailable: {type(e).__name__}'}
        st['enabled'] = cfg.enabled
        st['highlight'] = cfg.id == wanted
        rows.append(st)
    return rows


# ── pages ───────────────────────────────────────────────────────────

def _list_context(request: Request, auth: AuthContext, notice: str = '', error: str = '') -> Dict[str, Any]:
    return {'user': _user(auth), 'is_admin': auth.is_admin, 'is_user': _is_user(auth),
            'rows': _rows_for(auth.user_id) if _is_user(auth) else [], 'notice': notice, 'error': error,
            **_fed_state()}


@router.get('/account/server-connections', name='account_server_connections_page')
async def server_connections_page(request: Request, auth: AuthContext = Depends(require_auth)):
    q = request.query_params
    notice = ''
    if q.get('saved'):
        cfg = _config(q.get('saved', ''))
        notice = f'Connected to {cfg.display_title if cfg else q.get("saved")}. Its tools now act as you.'
    elif q.get('removed'):
        notice = 'Removed. SAJHA no longer holds a token of yours for that server.'
    return render(request, 'account/server_connections.html',
                  _list_context(request, auth, notice=notice, error=q.get('error', '')[:300]))


def _connect_context(request: Request, auth: AuthContext, cfg, error: str = '') -> Dict[str, Any]:
    st = _tokens().status_of(cfg, auth.user_id) if _is_user(auth) else {}
    return {'user': _user(auth), 'is_admin': auth.is_admin, 'is_user': _is_user(auth), 'csrf': csrf_token(request, auth),
            'server': {'id': cfg.id, 'title': cfg.display_title, 'url': cfg.url, 'enabled': cfg.enabled}, 'st': st,
            'error': error, **_fed_state()}


@router.get('/account/server-connections/{upstream_id}', name='account_server_connect_page')
async def server_connect_page(upstream_id: str, request: Request, auth: AuthContext = Depends(require_auth)):
    cfg = _config(upstream_id)
    if cfg is None:
        return render(request, 'account/server_connections.html',
                      _list_context(request, auth, error=f'No proxied server {upstream_id[:64]} signs users in '
                                                         f'with their own account.'), status_code=404)
    return render(request, 'account/server_connect.html', _connect_context(request, auth, cfg))


def _tester(cfg, test: bool):
    if not test:
        return None
    from sajha.federation.user_tokens import TokenUserSpec
    if not TokenUserSpec.from_auth(cfg.auth).test_call:
        return None
    m = _manager()
    return (lambda token: m.test_user_token(cfg.id, token)) if m is not None else None


@router.post('/account/server-connections/{upstream_id}/token')
async def server_connect_save(upstream_id: str, request: Request, auth: AuthContext = Depends(require_auth),
                              csrf: str = Form(''), token: str = Form(''), skip_test: str = Form('')):
    cfg = _config(upstream_id)
    if cfg is None:
        return RedirectResponse('/account/server-connections?' + urlencode({'error': 'Unknown server.'}),
                                status_code=303)
    if not _csrf_ok(request, auth, csrf):
        return render(request, 'account/server_connect.html',
                      _connect_context(request, auth, cfg, 'The form expired; reload the page and try again.'),
                      status_code=403)
    from sajha.federation.user_tokens import TokenRejected
    try:
        await asyncio.to_thread(_tokens().save, cfg, auth.user_id, token, actor=auth.user_id, ip=_ip(request),
                                tester=_tester(cfg, not skip_test))
    except TokenRejected as e:
        return render(request, 'account/server_connect.html', _connect_context(request, auth, cfg, str(e)),
                      status_code=400)
    return RedirectResponse('/account/server-connections?' + urlencode({'saved': cfg.id}), status_code=303)


@router.post('/account/server-connections/{upstream_id}/remove')
async def server_connect_remove(upstream_id: str, request: Request, auth: AuthContext = Depends(require_auth),
                                csrf: str = Form('')):
    if not _csrf_ok(request, auth, csrf):
        return render(request, 'account/server_connections.html',
                      _list_context(request, auth, error='The form expired; reload the page and try again.'),
                      status_code=403)
    await asyncio.to_thread(_tokens().remove, upstream_id, auth.user_id, actor=auth.user_id, ip=_ip(request))
    return RedirectResponse('/account/server-connections?removed=1', status_code=303)


# ── administration ──────────────────────────────────────────────────

def _admin_context(request: Request, auth: AuthContext, notice: str = '', error: str = '') -> Dict[str, Any]:
    upstream = request.query_params.get('server', '') or None
    user_id = request.query_params.get('user', '') or None
    rows: List[Dict[str, Any]] = []
    try:
        rows = _tokens().all_connections(upstream, user_id)
    except Exception as e:
        error = error or f'The token vault is unavailable: {e}'
    titles = {c.id: c.display_title for c in _per_user_configs()}
    for r in rows:
        r['title'] = titles.get(r['upstream'], r['upstream'])
    from sajha.federation.user_tokens import auth_mode
    servers = [{'id': c.id, 'title': c.display_title, 'mode': auth_mode(c),
                'connected': sum(1 for r in rows if r['upstream'] == c.id and r['status'] == 'connected')}
               for c in _per_user_configs()]
    return {'user': _user(auth), 'is_admin': True, 'csrf': csrf_token(request, auth), 'rows': rows,
            'servers': servers, 'filter_server': upstream or '', 'filter_user': user_id or '', 'notice': notice,
            'error': error, **_fed_state()}


@router.get('/admin/server-connections', name='admin_server_connections_page')
async def admin_server_connections_page(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/server_connections.html',
                  _admin_context(request, auth, notice=request.query_params.get('notice', '')[:300]))


@router.post('/admin/server-connections/revoke')
async def admin_server_connections_revoke(request: Request, auth: AuthContext = Depends(require_admin),
                                          csrf: str = Form(''), user_id: str = Form(''), upstream: str = Form('')):
    if not _csrf_ok(request, auth, csrf):
        return render(request, 'admin/server_connections.html',
                      _admin_context(request, auth, error='The form expired; reload the page and try again.'),
                      status_code=403)
    done = await asyncio.to_thread(_tokens().remove, upstream, user_id, actor=auth.user_id, ip=_ip(request),
                                   reason='revoked by an administrator')
    msg = f'Removed the {upstream} token of {user_id}.' if done else f'{user_id} had no token for {upstream}.'
    return RedirectResponse('/admin/server-connections?' + urlencode({'notice': msg}), status_code=303)


# ── JSON API ────────────────────────────────────────────────────────

def _csrf_api(request: Request, auth: AuthContext) -> Optional[JSONResponse]:
    if auth.auth_type == 'session' and not _csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
        return JSONResponse({'error': 'X-CSRF-Token missing or invalid'}, status_code=403)
    return None


@router.get('/api/accounts/server-connections')
async def api_server_connections(request: Request, auth: AuthContext = Depends(require_auth)):
    rows = await asyncio.to_thread(_rows_for, auth.user_id) if _is_user(auth) else []
    return JSONResponse({'connections': rows})


@router.put('/api/accounts/server-connections/{upstream_id}')
async def api_server_connection_save(upstream_id: str, request: Request, auth: AuthContext = Depends(require_auth)):
    bad = _csrf_api(request, auth)
    if bad is not None:
        return bad
    cfg = _config(upstream_id)
    if cfg is None:
        return JSONResponse({'error': f'no per-user proxied server {upstream_id[:64]}'}, status_code=404)
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse({'error': 'expected a JSON object with "token"'}, status_code=400)
    from sajha.federation.user_tokens import TokenRejected
    try:
        out = await asyncio.to_thread(_tokens().save, cfg, auth.user_id, str(body.get('token') or ''),
                                      actor=auth.user_id, ip=_ip(request),
                                      tester=_tester(cfg, body.get('test', True) is not False))
    except TokenRejected as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    return JSONResponse({'connection': out})


@router.delete('/api/accounts/server-connections/{upstream_id}')
async def api_server_connection_remove(upstream_id: str, request: Request, auth: AuthContext = Depends(require_auth)):
    bad = _csrf_api(request, auth)
    if bad is not None:
        return bad
    done = await asyncio.to_thread(_tokens().remove, upstream_id, auth.user_id, actor=auth.user_id, ip=_ip(request))
    return JSONResponse({'removed': done}, status_code=200 if done else 404)


@router.get('/api/admin/server-connections')
async def api_admin_server_connections(request: Request, auth: AuthContext = Depends(require_admin)):
    rows = await asyncio.to_thread(_tokens().all_connections, request.query_params.get('server') or None,
                                   request.query_params.get('user') or None)
    return JSONResponse({'connections': rows})


@router.delete('/api/admin/server-connections/{upstream_id}/{user_id}')
async def api_admin_server_connection_revoke(upstream_id: str, user_id: str, request: Request,
                                             auth: AuthContext = Depends(require_admin)):
    bad = _csrf_api(request, auth)
    if bad is not None:
        return bad
    done = await asyncio.to_thread(_tokens().remove, upstream_id, user_id, actor=auth.user_id, ip=_ip(request),
                                   reason='revoked by an administrator')
    return JSONResponse({'removed': done}, status_code=200 if done else 404)
