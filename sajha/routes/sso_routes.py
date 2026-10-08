"""
Console single sign-on routes (OpenID Connect; sajha/auth/sso.py).

    GET /auth/sso/login?next=/path   start: redirect to the identity provider
    GET /auth/sso/callback           the provider's answer: sign in, then redirect to next
    GET /api/auth/sso                whether SSO is on, its label and login URL (public)

Sign-out is GET /logout and POST /api/auth/logout (sajha/routes/auth_routes.py), which also
end the provider session when ``auth.sso.idp_logout`` is on.  Off unless ``auth.sso.enabled``.
docs/security/Security Model.md "Console single sign-on"

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from sajha.auth import sso
from sajha.db.engine import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=['auth'])


def _login_error(request: Request, message: str, status: int = 400):
    from sajha.app import render_standalone
    resp = render_standalone(request, 'auth/login.html', {'error': message, 'sso': sso.public_info()},
                             status_code=status)
    resp.delete_cookie(sso.BINDING_COOKIE, path='/auth/sso')
    return resp


@router.get('/api/auth/sso')
async def sso_info():
    return JSONResponse(sso.public_info())


@router.get('/auth/sso/login')
async def sso_login(request: Request):
    if not sso.enabled():
        return JSONResponse({'error': 'single sign-on is not enabled'}, status_code=404)
    try:
        url, binding = await sso.begin(request, request.query_params.get('next'))
    except sso.SSOError as e:
        logger.warning(f'SSO start failed: {e}')
        return _login_error(request, f'Single sign-on is unavailable: {e}', 502)
    except Exception as e:  # noqa: BLE001 - provider unreachable
        logger.warning(f'SSO start failed: {e}')
        return _login_error(request, 'Single sign-on is unavailable: the identity provider did not answer.', 502)
    from sajha.routes.auth_routes import cookie_secure
    resp = RedirectResponse(url, status_code=302)
    # Lax: the provider's redirect back is a cross-site top-level GET, which Lax cookies follow
    resp.set_cookie(sso.BINDING_COOKIE, binding, max_age=sso.STATE_TTL, httponly=True, samesite='lax',
                    secure=cookie_secure(request), path='/auth/sso')
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@router.get('/auth/sso/callback')
async def sso_callback(request: Request, db: Session = Depends(get_db)):
    if not sso.enabled():
        return JSONResponse({'error': 'single sign-on is not enabled'}, status_code=404)
    q = request.query_params
    from sajha.security import login_blocked, record_login_failure
    if login_blocked(request):
        return _login_error(request, 'Too many failed sign-in attempts from your address. Wait a few minutes and retry.', 429)
    try:
        rec = sso.take_state(q.get('state', ''), request.cookies.get(sso.BINDING_COOKIE))
        if q.get('error'):
            raise sso.SSOError('The identity provider did not sign you in'
                               + (f": {q.get('error_description') or q.get('error')}" if q.get('error') else '.'))
        code = q.get('code')
        if not code:
            raise sso.SSOError('The sign-in response has no code.')
        tokens = await sso.exchange_code(code, rec)
        claims = await sso.validate_id_token(tokens['id_token'], rec['nonce'], tokens.get('access_token'))
        user = sso.resolve_user(db, claims)
        token = sso.sign_in(db, user, claims, tokens['id_token'],
                            ip=request.client.host if request.client else None)
    except sso.SSOError as e:
        record_login_failure(request)
        logger.warning(f'SSO sign-in refused: {e}')
        from sajha.db.dao import AuditDAO
        try:
            AuditDAO(db).log('user.login_failed', None, 'user', None, details={'method': 'sso', 'reason': str(e)})
        except Exception:  # noqa: BLE001
            pass
        return _login_error(request, str(e), 403)
    except Exception as e:  # noqa: BLE001 - provider unreachable mid-flow
        logger.warning(f'SSO sign-in failed: {e}', exc_info=True)
        return _login_error(request, 'Single sign-on failed: the identity provider did not answer.', 502)
    from sajha.routes.auth_routes import start_session
    resp = RedirectResponse(sso.safe_next(rec.get('next')), status_code=302)
    start_session(request, resp, token)
    resp.delete_cookie(sso.BINDING_COOKIE, path='/auth/sso')
    resp.headers['Cache-Control'] = 'no-store'
    return resp
