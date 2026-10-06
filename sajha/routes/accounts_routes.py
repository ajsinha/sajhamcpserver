"""
SAJHA MCP Server — Connected accounts routes (per-user OAuth links to third-party services).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

    GET  /account/connections                         your linked accounts; Connect / Disconnect
    POST /account/connections/{provider}/connect      start the OAuth flow (CSRF) -> provider
    GET  /account/connections/{provider}/callback     the provider's redirect back (state, PKCE)
    POST /account/connections/{provider}/disconnect   revoke and forget (CSRF)
    GET  /admin/connections                           who linked what (never a token); revoke; re-encrypt
    POST /admin/connections/revoke                    an administrator unlinks a user's account (CSRF)
    POST /admin/connections/rotate                    re-encrypt every row with the current vault key (CSRF)
    GET  /api/accounts/connections                    JSON: providers and your connections
    DELETE /api/accounts/connections/{provider}       JSON: disconnect (X-CSRF-Token with a cookie session)
    GET  /api/admin/accounts/connections              JSON: every connection (admin; metadata only)

Pages that change state are POST forms carrying a CSRF token bound to the session cookie.
The flow start also sets ``sajha_acct_flow``, an HttpOnly nonce cookie whose hash is
stored with the flow's state, so a callback completes only in the browser that started it.

Design: docs/architecture/Connected Accounts.md
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from sajha.app import render
from sajha.auth import AuthContext, require_admin, require_auth

logger = logging.getLogger(__name__)

router = APIRouter(tags=['connected-accounts'])

FLOW_COOKIE = 'sajha_acct_flow'


# ── CSRF ────────────────────────────────────────────────────────────

def _csrf_key() -> bytes:
    from sajha.core.config import get_settings
    return hashlib.sha256(b'sajha-accounts-csrf|' + get_settings().secret_key.encode()).digest()


def csrf_token(request: Request, auth: AuthContext) -> str:
    cookie = request.cookies.get('sajha_token', '')
    binding = hashlib.sha256(cookie.encode()).hexdigest()
    return hmac.new(_csrf_key(), f'{auth.user_id}|{binding}'.encode(), hashlib.sha256).hexdigest()


def _csrf_ok(request: Request, auth: AuthContext, given: Optional[str]) -> bool:
    return bool(given) and hmac.compare_digest(str(given), csrf_token(request, auth))


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _service():
    from sajha.accounts.service import get_service
    return get_service()


def _user(auth: AuthContext) -> dict:
    return {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles}


def _is_user(auth: AuthContext) -> bool:
    from sajha.accounts.service import is_user_caller
    return auth.auth_type != 'apikey' and is_user_caller(auth.user_id)


def _accounts_enabled() -> bool:
    from sajha.accounts.settings import get_accounts_settings
    return get_accounts_settings().enabled


def _page_context(request: Request, auth: AuthContext, *, error: str = '', notice: str = '') -> dict:
    from sajha.accounts.providers import get_registry
    svc = _service()
    reg = get_registry()
    linked = {}
    vault_error = ''
    if _is_user(auth) and _accounts_enabled():
        try:
            linked = {c['provider']: c for c in svc.connections_for(auth.user_id)}
        except Exception as e:
            vault_error = f'The token vault is unavailable: {e}'
    wanted = request.query_params.get('connect', '')
    extra_scope = request.query_params.get('scope', '')
    providers = []
    for p in reg.all():
        if not p.configured and p.id not in linked:
            continue
        d = p.public_dict()
        d['connection'] = linked.get(p.id)
        d['highlight'] = p.id == wanted
        d['extra_scopes'] = extra_scope if p.id == wanted else ''
        if d['connection']:
            d['missing_scopes'] = p.missing_scopes(d['connection']['scopes'], extra_scope.split()) \
                if p.id == wanted and extra_scope else []
        providers.append(d)
    unconfigured = [p.public_dict() for p in reg.all() if not p.configured]
    return {
        'user': _user(auth), 'is_admin': auth.is_admin, 'csrf': csrf_token(request, auth),
        'providers': providers, 'unconfigured': unconfigured, 'is_user': _is_user(auth),
        'enabled': _accounts_enabled(), 'wanted': wanted, 'error': error or vault_error,
        'notice': notice, 'config_errors': reg.errors if auth.is_admin else {},
    }


# ── the account page ────────────────────────────────────────────────

@router.get('/account/connections', name='account_connections_page')
async def account_connections_page(request: Request, auth: AuthContext = Depends(require_auth)):
    notice = ''
    linked = request.query_params.get('linked')
    if linked:
        from sajha.accounts.providers import get_registry
        p = get_registry().get(linked)
        notice = f'{p.title if p else linked} is linked. Tools that act as you there can now run.'
    if request.query_params.get('disconnected'):
        notice = 'Disconnected. SAJHA no longer holds a token for that account.'
    return render(request, 'account/connections.html',
                  _page_context(request, auth, error=request.query_params.get('error', '')[:300], notice=notice))


@router.post('/account/connections/{provider}/connect')
async def account_connect(provider: str, request: Request, auth: AuthContext = Depends(require_auth),
                          csrf: str = Form(''), scope: str = Form(''), return_to: str = Form('')):
    if not _csrf_ok(request, auth, csrf):
        return render(request, 'account/connections.html',
                      _page_context(request, auth, error='The form expired; reload the page and try again.'),
                      status_code=403)
    if not _is_user(auth) or not _accounts_enabled():
        return render(request, 'account/connections.html',
                      _page_context(request, auth, error='Connected accounts belong to signed-in users.'),
                      status_code=403)
    from sajha.accounts.errors import AccountsError
    nonce = secrets.token_urlsafe(32)
    safe_return = return_to if return_to.startswith('/') and not return_to.startswith('//') else ''
    try:
        url = _service().start(auth.user_id, provider, browser_nonce=nonce, request=request,
                               scopes=[s for s in scope.split() if s][:20], return_to=safe_return)
    except AccountsError as e:
        return render(request, 'account/connections.html', _page_context(request, auth, error=str(e)),
                      status_code=400)
    from sajha.accounts.settings import get_accounts_settings
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(FLOW_COOKIE, nonce, max_age=get_accounts_settings().flow_ttl_seconds, httponly=True,
                    samesite='lax', secure=request.url.scheme == 'https', path='/account/connections')
    return resp


@router.get('/account/connections/{provider}/callback', name='account_connections_callback')
async def account_callback(provider: str, request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.accounts.errors import AccountsError
    q = request.query_params
    try:
        import asyncio
        out = await asyncio.to_thread(
            _service().complete, auth.user_id, provider, state=q.get('state', ''), code=q.get('code', ''),
            error=q.get('error', ''), error_description=q.get('error_description', ''),
            browser_nonce=request.cookies.get(FLOW_COOKIE, ''), ip=_ip(request))
    except AccountsError as e:
        resp = render(request, 'account/connections.html', _page_context(request, auth, error=str(e)),
                      status_code=400)
        resp.delete_cookie(FLOW_COOKIE, path='/account/connections')
        return resp
    target = out.get('return_to') or ('/account/connections?' + urlencode({'linked': provider}))
    resp = RedirectResponse(target, status_code=303)
    resp.delete_cookie(FLOW_COOKIE, path='/account/connections')
    return resp


@router.post('/account/connections/{provider}/disconnect')
async def account_disconnect(provider: str, request: Request, auth: AuthContext = Depends(require_auth),
                             csrf: str = Form('')):
    if not _csrf_ok(request, auth, csrf):
        return render(request, 'account/connections.html',
                      _page_context(request, auth, error='The form expired; reload the page and try again.'),
                      status_code=403)
    import asyncio
    await asyncio.to_thread(_service().disconnect, auth.user_id, provider, actor=auth.user_id, ip=_ip(request))
    return RedirectResponse('/account/connections?disconnected=1', status_code=303)


# ── JSON API ────────────────────────────────────────────────────────

@router.get('/api/accounts/connections')
async def api_my_connections(request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.accounts.providers import get_registry
    svc = _service()
    conns = svc.connections_for(auth.user_id) if _is_user(auth) and _accounts_enabled() else []
    return JSONResponse({'providers': [p.public_dict() for p in get_registry().configured()],
                         'connections': conns,
                         'connect_url': f'{request.base_url}account/connections'})


@router.delete('/api/accounts/connections/{provider}')
async def api_disconnect(provider: str, request: Request, auth: AuthContext = Depends(require_auth)):
    if auth.auth_type == 'session' and not _csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
        return JSONResponse({'error': 'X-CSRF-Token missing or invalid'}, status_code=403)
    import asyncio
    done = await asyncio.to_thread(_service().disconnect, auth.user_id, provider, actor=auth.user_id,
                                   ip=_ip(request))
    return JSONResponse({'disconnected': done}, status_code=200 if done else 404)


# ── administration ──────────────────────────────────────────────────

def _admin_context(request: Request, auth: AuthContext, notice: str = '', error: str = '') -> dict:
    from sajha.accounts.providers import get_registry
    from sajha.accounts.vault import get_vault
    reg = get_registry()
    provider = request.query_params.get('provider', '') or None
    user_id = request.query_params.get('user', '') or None
    rows, keys, current_kid = [], {}, ''
    try:
        vault = get_vault()
        rows = [c.to_public() for c in vault.list_all(provider=provider, user_id=user_id, limit=2000)]
        keys = vault.key_usage()
        current_kid = vault.keys.current()[0]
    except Exception as e:
        error = error or f'The token vault is unavailable: {e}'
    return {'user': _user(auth), 'is_admin': True, 'csrf': csrf_token(request, auth), 'rows': rows,
            'providers': [p.public_dict() for p in reg.all()], 'config_errors': reg.errors,
            'filter_provider': provider or '', 'filter_user': user_id or '', 'key_usage': keys,
            'current_key': current_kid, 'notice': notice, 'error': error, 'enabled': _accounts_enabled()}


@router.get('/admin/connections', name='admin_connections_page')
async def admin_connections_page(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/connections.html',
                  _admin_context(request, auth, notice=request.query_params.get('notice', '')[:300]))


@router.post('/admin/connections/revoke')
async def admin_revoke(request: Request, auth: AuthContext = Depends(require_admin), csrf: str = Form(''),
                       user_id: str = Form(''), provider: str = Form('')):
    if not _csrf_ok(request, auth, csrf):
        return render(request, 'admin/connections.html',
                      _admin_context(request, auth, error='The form expired; reload the page and try again.'),
                      status_code=403)
    import asyncio
    done = await asyncio.to_thread(_service().disconnect, user_id, provider, actor=auth.user_id, ip=_ip(request))
    msg = f'Unlinked {provider} for {user_id}.' if done else f'{user_id} had no {provider} link.'
    return RedirectResponse('/admin/connections?' + urlencode({'notice': msg}), status_code=303)


@router.post('/admin/connections/rotate')
async def admin_rotate(request: Request, auth: AuthContext = Depends(require_admin), csrf: str = Form('')):
    if not _csrf_ok(request, auth, csrf):
        return render(request, 'admin/connections.html',
                      _admin_context(request, auth, error='The form expired; reload the page and try again.'),
                      status_code=403)
    import asyncio
    from sajha.accounts.vault import get_vault
    out = await asyncio.to_thread(get_vault().rotate)
    _service().audit('connected_account_vault_rotated', auth.user_id, '*', _ip(request), **out)
    msg = f"Re-encrypted {out['rotated']} link(s) with the current key; {out['failed']} could not be decrypted."
    return RedirectResponse('/admin/connections?' + urlencode({'notice': msg}), status_code=303)


@router.get('/api/admin/accounts/connections')
async def api_admin_connections(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.accounts.vault import get_vault
    provider = request.query_params.get('provider') or None
    user_id = request.query_params.get('user') or None
    rows = [c.to_public() for c in get_vault().list_all(provider=provider, user_id=user_id, limit=5000)]
    return JSONResponse({'connections': rows})
