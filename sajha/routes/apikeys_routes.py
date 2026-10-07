"""
SAJHA MCP Server — API keys: the administrator's pages and the user's own keys.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Administrators manage every key at ``/admin/apikeys`` (and ``/api/admin/apikeys``); every
signed-in user manages their own at ``/account/apikeys`` (and ``/api/account/apikeys``).
Key management needs a signed-in user (a console session or a SAJHA JWT), never an API
key, so a stolen key cannot mint more. Browser (cookie) requests that change something
carry the page's CSRF token (``X-CSRF-Token`` header, or a ``csrf`` form field).

The rules (owners, default keys, revocation, persistent keys) are in sajha/auth/apikeys.py;
the guide is docs/security/Security Model.md.
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sajha.app import render
from sajha.auth import AuthContext, require_admin, require_auth
from sajha.auth import apikeys as svc
from sajha.db.engine import get_db

router = APIRouter(tags=['apikeys'])


# ── helpers ─────────────────────────────────────────────────────────

def csrf_token(request: Request, auth: AuthContext) -> str:
    from sajha.routes.accounts_routes import csrf_token as _token
    return _token(request, auth)


def csrf_ok(request: Request, auth: AuthContext, given: Optional[str]) -> bool:
    from sajha.routes.accounts_routes import _csrf_ok
    return _csrf_ok(request, auth, given)


def _signed_in(auth: AuthContext) -> bool:
    return auth.auth_type in ('jwt', 'session') and auth._user is not None


def _refuse(request: Request, auth: AuthContext) -> Optional[JSONResponse]:
    """None when this request may manage keys; otherwise the error response."""
    if not _signed_in(auth):
        return JSONResponse({'error': 'API keys are managed by a signed-in user (console session or SAJHA JWT), '
                                      'not with an API key.'}, status_code=403)
    if auth.auth_type == 'session' and request.method not in ('GET', 'HEAD') \
            and not csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
        return JSONResponse({'error': 'missing or wrong X-CSRF-Token (reload the page)'}, status_code=403)
    return None


async def _body(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _user_ctx(auth: AuthContext) -> dict:
    return {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles}


def _tool_list(data: dict) -> list:
    raw = data.get('tool_list', data.get('tools', []))
    if isinstance(raw, str):
        raw = [p for line in raw.splitlines() for p in line.split(',')]
    return [str(p).strip() for p in (raw or []) if str(p).strip()]


def _bad(e: Exception, status: int = 400) -> JSONResponse:
    return JSONResponse({'error': str(e)}, status_code=status)


def _user_by_id(db: Session, user_id: str):
    from sajha.db.dao import UserDAO
    return UserDAO(db).get_by_user_id(user_id) if user_id else None


def _tool_names() -> list:
    try:
        from sajha.app import tools_registry
        return sorted(tools_registry.tools.keys()) if tools_registry else []
    except Exception:
        return []


def _shown_once(raw: str, key) -> dict:
    return {'success': True, 'key': raw, 'apikey': svc.public(key),
            'note': 'Copy the key now: SAJHA stores only its hash and will not show it again.'}


# ── administrators: pages ───────────────────────────────────────────

@router.get('/admin/apikeys', name='apikeys_list')
@router.get('/admin/apikeys/', include_in_schema=False)
async def apikeys_list(request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    from sajha.db.models import ApiKey, User
    keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    rows = [svc.public(k) for k in keys]
    f_owner = request.query_params.get('owner', '').strip()
    f_status = request.query_params.get('status', '').strip()
    shown = [r for r in rows
             if (not f_owner or (f_owner == '-' and r['owner'] is None) or r['owner'] == f_owner)
             and (not f_status or r['status'] == f_status)]
    users = [u.user_id for u in db.query(User).order_by(User.user_id).all()]
    return render(request, 'admin/apikeys_list.html', {
        'user': _user_ctx(auth), 'is_admin': True, 'csrf': csrf_token(request, auth),
        'apikeys': shown, 'users': users, 'filter_owner': f_owner, 'filter_status': f_status,
        'stats': {
            'total': len(rows),
            'active': sum(1 for r in rows if r['status'] == 'active'),
            'unowned': sum(1 for r in rows if r['owner'] is None and r['status'] != 'revoked'),
            'persistent': sum(1 for r in rows if r['persistent']),
            'revoked': sum(1 for r in rows if r['status'] == 'revoked'),
        },
        'can_manage': _signed_in(auth),
    })


@router.get('/admin/apikeys/create', name='apikey_create_page')
async def apikey_create_page(request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    from sajha.db.models import User
    return render(request, 'admin/apikeys_create.html', {
        'user': _user_ctx(auth), 'is_admin': True, 'csrf': csrf_token(request, auth),
        'users': [u.user_id for u in db.query(User).order_by(User.user_id).all()],
        'available_tools': _tool_names(), 'can_manage': _signed_in(auth),
        'max_per_user': svc.max_per_user(),
    })


@router.get('/admin/apikeys/{key_id}/view', name='apikey_view')
async def apikey_view(key_id: str, request: Request, auth: AuthContext = Depends(require_admin),
                      db: Session = Depends(get_db)):
    from sajha.db.models import User
    key = svc.get_key(db, key_id)
    if not key:
        return render(request, 'common/error.html', {'error': 'Not Found', 'message': 'API key not found'},
                      status_code=404)
    return render(request, 'admin/apikeys_view.html', {
        'user': _user_ctx(auth), 'is_admin': True, 'csrf': csrf_token(request, auth),
        'apikey': svc.public(key), 'users': [u.user_id for u in db.query(User).order_by(User.user_id).all()],
        'can_manage': _signed_in(auth),
    })


# ── administrators: JSON ────────────────────────────────────────────

@router.get('/api/admin/apikeys')
async def api_admin_keys(request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    from sajha.db.models import ApiKey
    owner = request.query_params.get('owner')
    q = db.query(ApiKey).order_by(ApiKey.created_at.desc())
    rows = [svc.public(k) for k in q.all()]
    if owner == '-':
        rows = [r for r in rows if r['owner'] is None]
    elif owner:
        rows = [r for r in rows if r['owner'] == owner]
    return JSONResponse({'apikeys': rows})


async def _admin_create(request: Request, auth: AuthContext, db: Session):
    err = _refuse(request, auth)
    if err:
        return err
    data = await _body(request)
    owner = None
    if data.get('owner'):
        owner = _user_by_id(db, str(data['owner']))
        if owner is None:
            return JSONResponse({'error': f'no such user: {data["owner"]}'}, status_code=400)
    try:
        key, raw = svc.create_key(db, name=str(data.get('name') or ''), description=str(data.get('description') or ''),
                                  created_by=auth.user_id, owner=owner,
                                  mode=str(data.get('tool_access_mode') or 'all'), tool_list=_tool_list(data),
                                  expires_in_days=data.get('expires_in_days'),
                                  persistent=bool(data.get('persistent')))
    except svc.KeyError_ as e:
        return _bad(e)
    return JSONResponse(_shown_once(raw, key))


@router.post('/api/admin/apikeys')
async def api_admin_create(request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    """Body: name, description, owner (user ID; empty: an unowned key), tool_access_mode, tool_list,
    expires_in_days, persistent. The raw key is returned once."""
    return await _admin_create(request, auth, db)


@router.post('/admin/apikeys/create')
async def apikey_create(request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    """The older path of ``POST /api/admin/apikeys`` (same body and answer)."""
    return await _admin_create(request, auth, db)


def _admin_key(db: Session, key_id: str):
    key = svc.get_key(db, key_id)
    return key, (None if key else JSONResponse({'error': 'Not found'}, status_code=404))


@router.post('/api/admin/apikeys/{key_id}/rotate')
async def api_admin_rotate(key_id: str, request: Request, auth: AuthContext = Depends(require_admin),
                           db: Session = Depends(get_db)):
    err = _refuse(request, auth)
    if err:
        return err
    key, nf = _admin_key(db, key_id)
    if nf:
        return nf
    try:
        raw = svc.rotate_key(db, key, auth.user_id)
    except svc.KeyError_ as e:
        return _bad(e)
    return JSONResponse(_shown_once(raw, key))


@router.post('/api/admin/apikeys/{key_id}/revoke')
async def api_admin_revoke(key_id: str, request: Request, auth: AuthContext = Depends(require_admin),
                           db: Session = Depends(get_db)):
    err = _refuse(request, auth)
    if err:
        return err
    key, nf = _admin_key(db, key_id)
    if nf:
        return nf
    try:
        svc.revoke_key(db, key, auth.user_id)
    except svc.KeyError_ as e:
        return _bad(e)
    return JSONResponse({'success': True, 'apikey': svc.public(key)})


@router.post('/api/admin/apikeys/{key_id}/enabled')
async def api_admin_enabled(key_id: str, request: Request, auth: AuthContext = Depends(require_admin),
                            db: Session = Depends(get_db)):
    """Body: {"enabled": true|false}. A revoked key cannot be enabled again."""
    err = _refuse(request, auth)
    if err:
        return err
    key, nf = _admin_key(db, key_id)
    if nf:
        return nf
    data = await _body(request)
    try:
        svc.set_enabled(db, key, bool(data.get('enabled')), auth.user_id)
    except svc.KeyError_ as e:
        return _bad(e)
    return JSONResponse({'success': True, 'apikey': svc.public(key)})


@router.post('/admin/apikeys/{key_id}/toggle')
async def apikey_toggle(key_id: str, request: Request, auth: AuthContext = Depends(require_admin),
                        db: Session = Depends(get_db)):
    """The older enable/disable switch: flips ``enabled``."""
    err = _refuse(request, auth)
    if err:
        return err
    key, nf = _admin_key(db, key_id)
    if nf:
        return nf
    try:
        svc.set_enabled(db, key, not key.enabled, auth.user_id)
    except svc.KeyError_ as e:
        return _bad(e)
    return JSONResponse({'success': True, 'enabled': key.enabled})


@router.post('/api/admin/apikeys/{key_id}/owner')
async def api_admin_owner(key_id: str, request: Request, auth: AuthContext = Depends(require_admin),
                          db: Session = Depends(get_db)):
    """Body: {"owner": "<user ID>"}. Only for a key without an owner; it then signs in as that user."""
    err = _refuse(request, auth)
    if err:
        return err
    key, nf = _admin_key(db, key_id)
    if nf:
        return nf
    data = await _body(request)
    user = _user_by_id(db, str(data.get('owner') or ''))
    if user is None:
        return JSONResponse({'error': 'owner must be an existing user ID'}, status_code=400)
    try:
        svc.assign_owner(db, key, user, auth.user_id)
    except svc.KeyError_ as e:
        return _bad(e)
    return JSONResponse({'success': True, 'apikey': svc.public(key)})


@router.post('/api/admin/apikeys/{key_id}/persistent')
async def api_admin_persistent(key_id: str, request: Request, auth: AuthContext = Depends(require_admin),
                               db: Session = Depends(get_db)):
    """Body: {"persistent": true|false}: keep (or stop keeping) the key's hashed record in config.apikeys.path."""
    err = _refuse(request, auth)
    if err:
        return err
    key, nf = _admin_key(db, key_id)
    if nf:
        return nf
    data = await _body(request)
    try:
        svc.set_persistent(db, key, bool(data.get('persistent')), auth.user_id)
    except svc.KeyError_ as e:
        return _bad(e)
    return JSONResponse({'success': True, 'apikey': svc.public(key)})


@router.post('/api/admin/apikeys/{key_id}/access')
async def api_admin_access(key_id: str, request: Request, auth: AuthContext = Depends(require_admin),
                           db: Session = Depends(get_db)):
    """Body: {"tool_access_mode", "tool_list"}: the key's own tool access (a ceiling for an owned key)."""
    err = _refuse(request, auth)
    if err:
        return err
    key, nf = _admin_key(db, key_id)
    if nf:
        return nf
    data = await _body(request)
    try:
        svc.set_access(db, key, str(data.get('tool_access_mode') or 'all'), _tool_list(data), auth.user_id)
    except svc.KeyError_ as e:
        return _bad(e)
    return JSONResponse({'success': True, 'apikey': svc.public(key)})


async def _admin_delete(key_id: str, request: Request, auth: AuthContext, db: Session):
    err = _refuse(request, auth)
    if err:
        return err
    key, nf = _admin_key(db, key_id)
    if nf:
        return nf
    try:
        svc.delete_key(db, key, auth.user_id)
    except svc.KeyError_ as e:
        return _bad(e)
    return JSONResponse({'success': True})


@router.delete('/api/admin/apikeys/{key_id}')
async def api_admin_delete(key_id: str, request: Request, auth: AuthContext = Depends(require_admin),
                           db: Session = Depends(get_db)):
    """Remove a key and its record (not a default key). Prefer revoking: it keeps the record."""
    return await _admin_delete(key_id, request, auth, db)


@router.delete('/admin/apikeys/{key_id}/delete')
async def apikey_delete(key_id: str, request: Request, auth: AuthContext = Depends(require_admin),
                        db: Session = Depends(get_db)):
    """The older path of ``DELETE /api/admin/apikeys/{key_id}``."""
    return await _admin_delete(key_id, request, auth, db)


# ── every user: their own keys ──────────────────────────────────────

def _me(auth: AuthContext, db: Session):
    return _user_by_id(db, auth.user_id) if _signed_in(auth) else None


@router.get('/account/apikeys', name='account_apikeys_page')
async def account_apikeys_page(request: Request, auth: AuthContext = Depends(require_auth),
                               db: Session = Depends(get_db)):
    me = _me(auth, db)
    keys = []
    if me is not None:
        try:
            svc.ensure_default_key(db, me, by=me.user_id)
        except Exception:
            db.rollback()
        keys = [svc.public(k) for k in svc.keys_of(db, me)]
    error = {'signout': 'Signing out everywhere needs the page\'s form; reload and try again.'}.get(
        request.query_params.get('error', ''), '')
    return render(request, 'account/apikeys.html', {
        'user': _user_ctx(auth), 'is_admin': auth.is_admin, 'csrf': csrf_token(request, auth),
        'apikeys': keys, 'is_user': me is not None, 'max_per_user': svc.max_per_user(),
        'error': error,
    })


@router.get('/api/account/apikeys')
async def api_my_keys(request: Request, auth: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    me = _me(auth, db)
    if me is None:
        return JSONResponse({'error': 'Only a signed-in user has their own keys here.'}, status_code=403)
    return JSONResponse({'apikeys': [svc.public(k) for k in svc.keys_of(db, me)]})


@router.post('/api/account/apikeys')
async def api_my_create(request: Request, auth: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    """Body: name, description, tool_access_mode, tool_list, expires_in_days. The key signs in as you,
    limited to the tools you may use and, further, to the key's own tool access. Returned once."""
    err = _refuse(request, auth)
    if err:
        return err
    me = _me(auth, db)
    data = await _body(request)
    try:
        key, raw = svc.create_key(db, name=str(data.get('name') or ''), description=str(data.get('description') or ''),
                                  created_by=me.user_id, owner=me,
                                  mode=str(data.get('tool_access_mode') or 'all'), tool_list=_tool_list(data),
                                  expires_in_days=data.get('expires_in_days'))
    except svc.KeyError_ as e:
        return _bad(e)
    return JSONResponse(_shown_once(raw, key))


def _my_key(db: Session, me, key_id: str):
    key = svc.get_key(db, key_id)
    if key is None or me is None or key.owner_id != me.id:
        return None, JSONResponse({'error': 'Not found'}, status_code=404)
    return key, None


@router.post('/api/account/apikeys/{key_id}/rotate')
async def api_my_rotate(key_id: str, request: Request, auth: AuthContext = Depends(require_auth),
                        db: Session = Depends(get_db)):
    err = _refuse(request, auth)
    if err:
        return err
    me = _me(auth, db)
    key, nf = _my_key(db, me, key_id)
    if nf:
        return nf
    try:
        raw = svc.rotate_key(db, key, me.user_id)
    except svc.KeyError_ as e:
        return _bad(e)
    return JSONResponse(_shown_once(raw, key))


@router.post('/api/account/apikeys/{key_id}/revoke')
async def api_my_revoke(key_id: str, request: Request, auth: AuthContext = Depends(require_auth),
                        db: Session = Depends(get_db)):
    err = _refuse(request, auth)
    if err:
        return err
    me = _me(auth, db)
    key, nf = _my_key(db, me, key_id)
    if nf:
        return nf
    try:
        svc.revoke_key(db, key, me.user_id)
    except svc.KeyError_ as e:
        return _bad(e)
    return JSONResponse({'success': True, 'apikey': svc.public(key)})
