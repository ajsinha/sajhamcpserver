"""
SAJHA MCP Server — admin pages for the administrators' credential files.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``/admin/apikeys/file`` manages ``config/apikeys.json`` and ``/admin/users/file`` manages
``config/users.json``. Both files win over the database (sajha/auth/persistent_keys.py,
sajha/auth/users_file.py). Administrators only, signed in with a console session (CSRF) or a
SAJHA JWT, never with an API key. Keys are masked in lists; revealing one is audited.
Passwords are never returned. Every change is written atomically and audited; a users-file
change is applied to the database at once.

JSON API (same rules): GET /api/admin/apikeys/file, POST (new key, shown once),
PUT /api/admin/apikeys/file/{id}, DELETE /api/admin/apikeys/file/{id},
GET /api/admin/apikeys/file/{id}/reveal; GET /api/admin/users/file, POST,
PUT /api/admin/users/file/{user_id}, DELETE /api/admin/users/file/{user_id}.
Guide: docs/security/Security Model.md ("Credential storage and files").
"""

from __future__ import annotations

import secrets
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sajha.app import render
from sajha.auth import AuthContext, require_admin
from sajha.db.engine import get_db
from sajha.routes.apikeys_routes import _refuse, _user_ctx, csrf_token

router = APIRouter(tags=['credential-files'])

KEY_FIELDS = ('name', 'owner', 'owner_name', 'roles', 'enabled', 'expires_at', 'tool_access_mode',
              'tool_access_list', 'test_admin')
MODES = ('all', 'allowlist', 'denylist', 'regex')


def _audit(db: Session, auth: AuthContext, action: str, rid: str, details: Optional[dict] = None) -> None:
    try:
        from sajha.db.dao import AuditDAO
        AuditDAO(db).log(action=action, user_id=auth.user_id, resource_type='credential_file',
                         resource_id=rid, details=details or {})
    except Exception:
        db.rollback()


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _mask(raw: Any) -> str:
    raw = str(raw or '')
    return (raw[:8] + '…' + raw[-4:]) if len(raw) > 14 else ('…' if raw else '')


# ── API keys file ──────────────────────────────────────────────────

def _keys():
    from sajha.auth.persistent_keys import get_persistent_keys
    return get_persistent_keys()


def _key_public(r: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: r.get(k) for k in ('id', *KEY_FIELDS)}
    out['masked'] = _mask(r['key']) if r.get('key') else ('sha256 ' + str(r.get('sha256', ''))[:8] + '…')
    out['form'] = 'raw' if r.get('key') else 'hash'
    return out


def _clean_key(data: Dict[str, Any], base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    rec = dict(base or {})
    for k in KEY_FIELDS:
        if k in data:
            rec[k] = data[k]
    rec['name'] = str(rec.get('name') or 'Unnamed key')[:255]
    roles = rec.get('roles') or []
    rec['roles'] = [str(x) for x in roles] if isinstance(roles, list) else [s.strip() for s in str(roles).split(',') if s.strip()]
    rec['enabled'] = bool(rec.get('enabled', True))
    rec['test_admin'] = bool(rec.get('test_admin', False))
    mode = str(rec.get('tool_access_mode') or 'all')
    if mode not in MODES:
        raise ValueError(f'tool_access_mode must be one of {", ".join(MODES)}')
    rec['tool_access_mode'] = mode
    tl = rec.get('tool_access_list') or []
    rec['tool_access_list'] = [str(x) for x in tl] if isinstance(tl, list) else [s.strip() for s in str(tl).split(',') if s.strip()]
    if not rec['test_admin']:
        rec.pop('test_admin', None)
    return rec


@router.get('/admin/apikeys/file', name='apikeys_file_page')
async def apikeys_file_page(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'admin/credential_file.html', {
        'user': _user_ctx(auth), 'is_admin': True, 'csrf': csrf_token(request, auth), 'kind': 'keys',
        'path': str(_keys().config_path)})


@router.get('/api/admin/apikeys/file')
async def apikeys_file_list(request: Request, auth: AuthContext = Depends(require_admin)):
    bad = _refuse(request, auth)
    if bad:
        return bad
    return {'path': str(_keys().config_path), 'keys': [_key_public(r) for r in _keys().records()]}


@router.post('/api/admin/apikeys/file')
async def apikeys_file_create(request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    bad = _refuse(request, auth)
    if bad:
        return bad
    data = await _body(request)
    try:
        rec = _clean_key(data)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    raw = str(data.get('key') or '').strip() or ('sja_' + secrets.token_hex(24))
    rec.update({'id': 'file-' + secrets.token_hex(8), 'key': raw, 'prefix': raw[:8], 'created_by': auth.user_id})
    _keys().upsert(rec)
    _audit(db, auth, 'apikeys_file.create', rec['id'], {'name': rec['name'], 'test_admin': bool(rec.get('test_admin'))})
    _standing()
    return {'key': _key_public(rec), 'raw': raw}


@router.put('/api/admin/apikeys/file/{kid}')
async def apikeys_file_update(kid: str, request: Request, auth: AuthContext = Depends(require_admin),
                              db: Session = Depends(get_db)):
    bad = _refuse(request, auth)
    if bad:
        return bad
    cur = next((r for r in _keys().records() if r.get('id') == kid), None)
    if cur is None:
        return JSONResponse({'error': 'no such key in the file'}, status_code=404)
    data = await _body(request)
    try:
        rec = _clean_key(data, cur)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    if str(data.get('key') or '').strip():
        rec['key'] = str(data['key']).strip()
        rec['prefix'] = rec['key'][:8]
        rec.pop('sha256', None)
    _keys().upsert(rec)
    _audit(db, auth, 'apikeys_file.update', kid, {k: rec.get(k) for k in ('name', 'enabled', 'test_admin')})
    _standing()
    return {'key': _key_public(rec)}


@router.delete('/api/admin/apikeys/file/{kid}')
async def apikeys_file_delete(kid: str, request: Request, auth: AuthContext = Depends(require_admin),
                              db: Session = Depends(get_db)):
    bad = _refuse(request, auth)
    if bad:
        return bad
    if not _keys().remove(kid):
        return JSONResponse({'error': 'no such key in the file'}, status_code=404)
    _audit(db, auth, 'apikeys_file.delete', kid)
    _standing()
    return {'deleted': kid}


@router.get('/api/admin/apikeys/file/{kid}/reveal')
async def apikeys_file_reveal(kid: str, request: Request, auth: AuthContext = Depends(require_admin),
                              db: Session = Depends(get_db)):
    bad = _refuse(request, auth)
    if bad:
        return bad
    cur = next((r for r in _keys().records() if r.get('id') == kid), None)
    if cur is None or not cur.get('key'):
        return JSONResponse({'error': 'no raw key to reveal (the record holds only a hash)'}, status_code=404)
    _audit(db, auth, 'apikeys_file.reveal', kid)
    return {'id': kid, 'key': cur['key']}


# ── users file ─────────────────────────────────────────────────────

def _users():
    from sajha.auth.users_file import get_users_file
    return get_users_file()


def _user_public(u: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: u.get(k) for k in ('user_id', 'user_name', 'email', 'roles', 'enabled', 'test_admin')}
    out['has_password'] = bool(u.get('password'))
    return out


def _apply(db: Session) -> list:
    from sajha.auth.users_file import sync_to_database
    _, problems = sync_to_database(db, _users())
    _standing()
    return problems


def _standing() -> None:
    try:
        from sajha.auth.credential_jobs import standing_notices
        standing_notices()
    except Exception:
        pass


def _known_roles(db: Session) -> set:
    from sajha.db.models import Role
    return {r.name for r in db.query(Role).all()}


@router.get('/admin/users/file', name='users_file_page')
async def users_file_page(request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    return render(request, 'admin/credential_file.html', {
        'user': _user_ctx(auth), 'is_admin': True, 'csrf': csrf_token(request, auth), 'kind': 'users',
        'path': str(_users().path), 'roles': sorted(_known_roles(db))})


@router.get('/api/admin/users/file')
async def users_file_list(request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    bad = _refuse(request, auth)
    if bad:
        return bad
    return {'path': str(_users().path), 'roles': sorted(_known_roles(db)),
            'users': [_user_public(u) for u in _users().users()]}


async def _save_user(request: Request, auth: AuthContext, db: Session, uid: Optional[str]):
    from sajha.auth.users_file import problem
    data = await _body(request)
    cur = _users().get(uid) if uid else None
    if uid and cur is None:
        return JSONResponse({'error': 'no such user in the file'}, status_code=404)
    rec = dict(cur or {})
    for k in ('user_id', 'user_name', 'email', 'roles', 'enabled', 'test_admin'):
        if k in data:
            rec[k] = data[k]
    if uid:
        rec['user_id'] = uid
    if str(data.get('password') or ''):
        rec['password'] = str(data['password'])
    if isinstance(rec.get('roles'), str):
        rec['roles'] = [s.strip() for s in rec['roles'].split(',') if s.strip()]
    rec['enabled'] = bool(rec.get('enabled', True))
    if not rec.get('test_admin'):
        rec.pop('test_admin', None)
    why = problem(rec, _known_roles(db))
    if why:
        return JSONResponse({'error': why}, status_code=400)
    if not uid and _users().get(rec['user_id']) is not None:
        return JSONResponse({'error': f'{rec["user_id"]} is already in the file'}, status_code=400)
    _users().upsert(rec)
    _audit(db, auth, 'users_file.update' if uid else 'users_file.create', rec['user_id'],
           {'roles': rec.get('roles'), 'enabled': rec['enabled'], 'password_changed': bool(data.get('password'))})
    problems = _apply(db)
    return {'user': _user_public(rec), 'problems': problems}


@router.post('/api/admin/users/file')
async def users_file_create(request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    bad = _refuse(request, auth)
    return bad or await _save_user(request, auth, db, None)


@router.put('/api/admin/users/file/{uid}')
async def users_file_update(uid: str, request: Request, auth: AuthContext = Depends(require_admin),
                            db: Session = Depends(get_db)):
    bad = _refuse(request, auth)
    return bad or await _save_user(request, auth, db, uid)


@router.delete('/api/admin/users/file/{uid}')
async def users_file_delete(uid: str, request: Request, auth: AuthContext = Depends(require_admin),
                            db: Session = Depends(get_db)):
    bad = _refuse(request, auth)
    if bad:
        return bad
    if not _users().remove(uid):
        return JSONResponse({'error': 'no such user in the file'}, status_code=404)
    _audit(db, auth, 'users_file.delete', uid)
    return {'deleted': uid, 'note': 'removed from the file; the database user is no longer managed by it'}
