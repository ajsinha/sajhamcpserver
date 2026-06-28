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
from sajha.auth import AuthManager, get_current_user, AuthContext
from sajha.app import render

router = APIRouter(tags=['auth'])


@router.get('/login')
async def login_page(request: Request):
    """Render login page."""
    from sajha.app import render_standalone
    return render_standalone(request, 'auth/login.html', {
        'error': None,
    })


@router.post('/login')
async def login_form(
    request: Request,
    db: Session = Depends(get_db),
    user_id: str = Form(...),
    password: str = Form(...),
):
    """Handle login form submission (web UI)."""
    token = AuthManager.authenticate_local(db, user_id, password)

    if not token:
        from sajha.app import render_standalone
        return render_standalone(request, 'auth/login.html', {
            'error': 'Invalid credentials',
        })

    # Set JWT in cookie and redirect to dashboard
    next_url = request.query_params.get('next', '/dashboard')
    response = RedirectResponse(url=next_url, status_code=302)
    response.set_cookie(
        key='sajha_token',
        value=token,
        httponly=True,
        samesite='lax',
        secure=request.url.scheme == 'https',
        max_age=3600,
    )
    return response


@router.post('/api/auth/login')
async def api_login(request: Request, db: Session = Depends(get_db)):
    from sajha.security import check_auth_rate_limit
    if not check_auth_rate_limit(request):
        from fastapi.responses import JSONResponse
        return JSONResponse({'error': 'Too many login attempts. Try again in 60 seconds.'}, status_code=429)
    """API login endpoint — returns JWT token."""
    data = await request.json()
    user_id = data.get('user_id') or data.get('username') or data.get('uid')
    password = data.get('password')

    if not user_id or not password:
        return JSONResponse({'error': 'Missing credentials'}, status_code=400)

    token = AuthManager.authenticate_local(db, user_id, password)
    if not token:
        return JSONResponse({'error': 'Invalid credentials'}, status_code=401)

    # Also decode to get user info for response
    auth_ctx = AuthManager.authenticate_jwt(db, token)
    return JSONResponse({
        'token': token,
        'user': {
            'user_id': auth_ctx.user_id,
            'user_name': auth_ctx.user_name,
            'roles': auth_ctx.roles,
        }
    })


@router.get('/logout')
async def logout(request: Request):
    """Logout — clear session cookie."""
    response = RedirectResponse(url='/', status_code=302)
    response.delete_cookie('sajha_token')
    return response


# ── Landing page or dashboard ────────────────────────────────────

@router.get('/')
async def root(request: Request, auth: AuthContext = Depends(get_current_user)):
    if auth.authenticated:
        return RedirectResponse(url='/dashboard', status_code=302)
    # Show landing page for unauthenticated visitors
    from sajha.app import render_standalone
    return render_standalone(request, 'landing.html', {})
