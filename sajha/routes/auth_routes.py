"""
SAJHA MCP Server v3 — Authentication Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Handles: login page, login POST (form + API), logout.
Sets JWT in both cookie (for web UI) and response body (for API clients).
"""

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from sajha.db.engine import get_db
from sajha.auth import AuthManager, get_current_user, require_auth, require_admin, AuthContext
from sajha.app import render

router = APIRouter(tags=['auth'])


@router.get('/login')
async def login_page(request: Request):
    """Render login page."""
    from sajha.app import render_standalone
    return render_standalone(request, 'auth/login.html', {
        'error': None,
    })


_LOCKED_MSG = 'Too many failed sign-ins for this account. Try again later.'
_THROTTLED_MSG = 'Too many failed sign-in attempts from your address. Wait a few minutes and retry.'


def _set_session_cookie(request: Request, response, token: str) -> None:
    response.set_cookie(
        key='sajha_token',
        value=token,
        httponly=True,
        samesite='lax',
        secure=request.url.scheme == 'https',
        max_age=3600,
    )


@router.post('/login')
async def login_form(
    request: Request,
    db: Session = Depends(get_db),
    user_id: str = Form(...),
    password: str = Form(...),
):
    """Handle login form submission (web UI): IP throttle + account lockout."""
    from sajha.app import render_standalone
    from sajha.security import login_blocked, record_login_failure
    if login_blocked(request):
        return render_standalone(request, 'auth/login.html', {'error': _THROTTLED_MSG}, status_code=429)

    token, outcome = AuthManager.sign_in(db, user_id, password)

    if not token:
        record_login_failure(request)
        return render_standalone(request, 'auth/login.html', {
            'error': _LOCKED_MSG if outcome == 'locked' else 'Invalid credentials',
        }, status_code=423 if outcome == 'locked' else 200)

    # Set JWT in cookie and redirect to dashboard
    next_url = request.query_params.get('next', '/dashboard')
    # Local paths only: no open redirect via ?next=https://evil or //evil
    if not next_url.startswith('/') or next_url.startswith(('//', '/\\')) or '\\' in next_url:
        next_url = '/dashboard'
    response = RedirectResponse(url=next_url, status_code=302)
    _set_session_cookie(request, response, token)
    return response


@router.post('/api/auth/login')
async def api_login(request: Request, db: Session = Depends(get_db)):
    """API login endpoint — returns JWT token.  IP throttle + account lockout."""
    from sajha.security import login_blocked, record_login_failure
    if login_blocked(request):
        return JSONResponse({'error': _THROTTLED_MSG}, status_code=429)
    try:
        data = await request.json()
    except ValueError:
        return JSONResponse({'error': 'JSON body required'}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({'error': 'JSON object body required'}, status_code=400)
    user_id = data.get('user_id') or data.get('username') or data.get('uid')
    password = data.get('password')

    if not user_id or not password:
        return JSONResponse({'error': 'Missing credentials'}, status_code=400)

    token, outcome = AuthManager.sign_in(db, str(user_id), str(password))
    if not token:
        record_login_failure(request)
        if outcome == 'locked':
            return JSONResponse({'error': _LOCKED_MSG}, status_code=423)
        return JSONResponse({'error': 'Invalid credentials'}, status_code=401)

    # Also decode to get user info for response
    auth_ctx = AuthManager.authenticate_jwt(db, token)
    return JSONResponse({
        'token': token,
        'user': {
            'user_id': auth_ctx.user_id,
            'user_name': auth_ctx.user_name,
            'roles': auth_ctx.roles,
        },
        'password_change_required': auth_ctx.password_change_required,
    })


# ── Change password (signed-in user) and admin reset ─────────────

def _change_password(db: Session, auth: AuthContext, current: str, new: str, confirm=None):
    """Returns (error message or None, new JWT or None)."""
    from sajha.auth.password import verify_password, hash_password, password_problem
    from sajha.db.dao import UserDAO, AuditDAO
    if auth.auth_type not in ('jwt', 'session') or auth._user is None:
        return 'Only a signed-in user can change a password (not an API key).', None
    user = UserDAO(db).get_by_user_id(auth.user_id)
    if user is None or not verify_password(current or '', user.password_hash):
        return 'The current password is wrong.', None
    if confirm is not None and new != confirm:
        return 'The new passwords do not match.', None
    problem = password_problem(new or '', user.user_id)
    if problem:
        return f'The new password {problem}.', None
    if verify_password(new, user.password_hash):
        return 'The new password must differ from the current one.', None
    user.password_hash = hash_password(new)
    user.must_change_password = False
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
    AuditDAO(db).log('user.password_change', user.user_id, 'user', user.user_id)
    # every other session ends; this one continues with a fresh token (revocable sign-in)
    from sajha.auth.revocation import end_all_sessions
    tv = end_all_sessions(db, user, user.user_id, 'password_change')
    from sajha.auth.jwt_handler import create_access_token
    return None, create_access_token(user.user_id, user.role_names, token_version=tv)


@router.get('/account/password', name='change_password_page')
async def change_password_page(request: Request, auth: AuthContext = Depends(require_auth)):
    return render(request, 'auth/change_password.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'required': auth.password_change_required,
        'can_change': auth.auth_type in ('jwt', 'session'),
        'error': None, 'done': False,
    })


@router.post('/account/password')
async def change_password_form(
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
    current_password: str = Form(''),
    new_password: str = Form(''),
    confirm_password: str = Form(''),
):
    error, token = _change_password(db, auth, current_password, new_password, confirm_password)
    ctx = {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'required': bool(error) and auth.password_change_required,
        'can_change': auth.auth_type in ('jwt', 'session'),
        'error': error, 'done': error is None,
    }
    if token:
        # The new cookie drops the "must change" flag; render with it so the banner goes too
        ctx['session'] = {'token': token}
    response = render(request, 'auth/change_password.html', ctx, status_code=400 if error else 200)
    if token:
        _set_session_cookie(request, response, token)
    return response


@router.post('/api/auth/change-password')
async def api_change_password(request: Request, auth: AuthContext = Depends(require_auth),
                              db: Session = Depends(get_db)):
    """Body: {"current_password": ..., "new_password": ...}.  Returns a fresh JWT."""
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return JSONResponse({'error': 'JSON object body required'}, status_code=400)
    error, token = _change_password(db, auth, str(data.get('current_password') or ''),
                                    str(data.get('new_password') or ''))
    if error:
        return JSONResponse({'error': error}, status_code=400)
    response = JSONResponse({'success': True, 'token': token})
    if auth.auth_type == 'session':
        _set_session_cookie(request, response, token)
    return response


@router.post('/api/admin/users/{uid}/password')
async def api_admin_reset_password(uid: str, request: Request, auth: AuthContext = Depends(require_admin),
                                   db: Session = Depends(get_db)):
    """
    Admin password reset.  Body: {"password": ..., "must_change_password": true}.
    Also unlocks the account.  The user must change the password at next sign-in unless
    must_change_password is false.
    """
    from sajha.auth.password import hash_password, password_problem
    from sajha.db.dao import UserDAO, AuditDAO
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return JSONResponse({'error': 'JSON object body required'}, status_code=400)
    user = UserDAO(db).get_by_user_id(uid)
    if user is None:
        return JSONResponse({'error': 'User not found'}, status_code=404)
    password = data.get('password')
    problem = password_problem(password if isinstance(password, str) else '', uid)
    if problem:
        return JSONResponse({'error': f'password: {problem}'}, status_code=400)
    user.password_hash = hash_password(password)
    user.must_change_password = bool(data.get('must_change_password', True))
    user.failed_attempts = 0
    user.locked_until = None
    db.commit()
    AuditDAO(db).log('user.password_reset', auth.user_id, 'user', uid)
    from sajha.auth.revocation import end_all_sessions
    end_all_sessions(db, user, auth.user_id, 'password_reset')
    return JSONResponse({'success': True, 'user_id': uid,
                         'must_change_password': user.must_change_password})


def _revoke_presented_token(request: Request) -> bool:
    """Sign-out: the cookie's (or bearer) SAJHA JWT stops working everywhere until it expires."""
    from sajha.auth.jwt_handler import decode_access_token
    from sajha.auth.revocation import revoke_token
    header = request.headers.get('Authorization', '')
    token = header[7:] if header.startswith('Bearer ') else request.cookies.get('sajha_token', '')
    payload = decode_access_token(token) if token else None
    return revoke_token(payload) if payload else False


@router.get('/logout')
async def logout(request: Request):
    """Logout — the session token is revoked (not only the cookie cleared)."""
    _revoke_presented_token(request)
    response = RedirectResponse(url='/', status_code=302)
    response.delete_cookie('sajha_token')
    return response


@router.post('/api/auth/logout')
async def api_logout(request: Request):
    """Revoke the presented SAJHA JWT (``Authorization: Bearer`` or the cookie)."""
    revoked = _revoke_presented_token(request)
    response = JSONResponse({'success': True, 'revoked': revoked})
    response.delete_cookie('sajha_token')
    return response


def _session_user(auth: AuthContext, db: Session):
    from sajha.db.dao import UserDAO
    if auth.auth_type not in ('jwt', 'session') or auth._user is None:
        return None
    return UserDAO(db).get_by_user_id(auth.user_id)


@router.post('/api/auth/sessions/revoke')
async def api_sign_out_everywhere(request: Request, auth: AuthContext = Depends(require_auth),
                                  db: Session = Depends(get_db)):
    """Sign out everywhere: every SAJHA JWT and built-in OAuth token of this user stops working,
    including the one making this request. Signed-in users only (not API keys)."""
    user = _session_user(auth, db)
    if user is None:
        return JSONResponse({'error': 'Only a signed-in user can end their sessions (not an API key).'},
                            status_code=403)
    if auth.auth_type == 'session':
        from sajha.routes.apikeys_routes import csrf_ok
        if not csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
            return JSONResponse({'error': 'missing or wrong X-CSRF-Token'}, status_code=403)
    from sajha.auth.revocation import end_all_sessions
    end_all_sessions(db, user, user.user_id, 'sign_out_everywhere')
    response = JSONResponse({'success': True})
    response.delete_cookie('sajha_token')
    return response


@router.post('/account/sessions/revoke')
async def account_sign_out_everywhere(request: Request, auth: AuthContext = Depends(require_auth),
                                      db: Session = Depends(get_db), csrf: str = Form('')):
    """The "Sign out everywhere" button (account API keys page): ends every session, then the login page."""
    from sajha.routes.apikeys_routes import csrf_ok
    user = _session_user(auth, db)
    if user is None or not csrf_ok(request, auth, csrf):
        return RedirectResponse(url='/account/apikeys?error=signout', status_code=303)
    from sajha.auth.revocation import end_all_sessions
    end_all_sessions(db, user, user.user_id, 'sign_out_everywhere')
    response = RedirectResponse(url='/login', status_code=303)
    response.delete_cookie('sajha_token')
    return response


@router.post('/api/admin/users/{uid}/sessions/revoke')
async def api_admin_revoke_sessions(uid: str, auth: AuthContext = Depends(require_admin),
                                    db: Session = Depends(get_db)):
    """Administrators: end every session (SAJHA JWTs, built-in OAuth tokens) of a user."""
    from sajha.db.dao import UserDAO
    from sajha.auth.revocation import end_all_sessions
    if auth.auth_type == 'apikey':
        return JSONResponse({'error': 'Sign in to manage sessions; API keys cannot.'}, status_code=403)
    user = UserDAO(db).get_by_user_id(uid)
    if user is None:
        return JSONResponse({'error': 'User not found'}, status_code=404)
    tv = end_all_sessions(db, user, auth.user_id, 'admin_revoke')
    return JSONResponse({'success': True, 'user_id': uid, 'token_version': tv})


# ── Landing page or dashboard ────────────────────────────────────

def _llm_provider_count() -> int:
    """Registered LLM provider types (sajha/ai/llm/registry.py), not counting the offline mock."""
    try:
        from sajha.ai.llm.registry import registered_providers
        return len([n for n in registered_providers() if n != 'mock'])
    except Exception:
        return 0


def _db_table_count() -> int:
    try:
        from sajha.db.models import Base
        return len(Base.metadata.tables)
    except Exception:
        return 0


@router.get('/')
async def root(request: Request, auth: AuthContext = Depends(get_current_user)):
    if auth.authenticated:
        return RedirectResponse(url='/dashboard', status_code=302)
    # Show landing page for unauthenticated visitors. The counts and the hero's constellation
    # come from the live registry, grouped by name prefix exactly as the help pages group them.
    from sajha.app import render_standalone
    from sajha.auth.access import anonymous_policy
    from sajha.web.help_catalog import live_tool_groups
    # names (a hover on a star names its tool) only for tools an anonymous MCP caller may
    # see; every other star is drawn from the counts alone
    live = live_tool_groups(with_names=True, visible=anonymous_policy().can_see)
    return render_standalone(request, 'landing.html', {
        'llm_provider_count': _llm_provider_count(),
        'db_table_count': _db_table_count(),
        'endpoint_count': len({(getattr(r, 'path', ''), m) for r in request.app.routes
                               for m in (getattr(r, 'methods', None) or ())}),
        'tool_count': live['total_tools'],
        'group_count': live['total_groups'],
        'tool_groups': [[g['name'], g['tool_count'], g['tools']] for g in live['groups']],
    })
