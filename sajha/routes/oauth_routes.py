"""
SAJHA MCP Server — OAuth 2.1 endpoints for MCP authorization.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Resource server (mcp.auth.mode optional|required):
  GET /.well-known/oauth-protected-resource[/mcp|/api/mcp]   RFC 9728

Built-in authorization server (mcp.auth.authorization_server: builtin):
  GET  /.well-known/oauth-authorization-server   RFC 8414
  GET  /oauth/authorize    consent page (authorization code + PKCE S256)
  POST /oauth/authorize    consent decision -> redirect with code, state, iss (RFC 9207)
  POST /oauth/token        authorization_code | refresh_token (rotating)
  GET  /oauth/jwks         public signing key
  POST /oauth/register     RFC 7591, only with dynamic_client_registration: true

Everything here answers 404 while mcp.auth.mode is off (the default), so
clients see "no OAuth" exactly as before.  No OpenID Connect discovery is
published: the server issues no ID tokens.
"""

import base64
import json
import logging
import secrets
import uuid
from typing import Dict, Optional
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from sajha.auth.oauth import settings
from sajha.auth.oauth import authorization_server as asrv
from sajha.auth.oauth.clients import ClientError, OAuthClient, get_client_registry, is_url_client_id
from sajha.auth.oauth.resource_server import PRM_PATH, protected_resource_metadata
from sajha.db.engine import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=['oauth'])

_TXN_COOKIE = 'sajha_oauth_txn'
_NO_STORE = {'Cache-Control': 'no-store', 'Pragma': 'no-cache'}
_SCOPE_TEXT = {
    'mcp': 'Full access to this MCP server as you',
    'mcp:read': 'List and read tools, prompts and resources',
    'mcp:tools': 'Run tools on your behalf',
    'offline_access': 'Stay signed in (refresh tokens)',
}


def _not_found() -> JSONResponse:
    return JSONResponse({'error': 'not_found'}, status_code=404)


def _builtin_active() -> bool:
    return settings.oauth_enabled() and settings.is_builtin()


def _doc_cache_headers() -> Dict[str, str]:
    """Discovery documents built from the request's Host (no mcp.auth.public_url) are never shared-cached."""
    if (settings._get('mcp.auth.public_url', '') or '').strip():
        return {'Cache-Control': 'public, max-age=300'}
    return {'Cache-Control': 'no-store', 'Vary': 'Host'}


def _json(doc: Dict, status: int = 200, headers: Optional[Dict] = None) -> JSONResponse:
    return JSONResponse(doc, status_code=status, headers=headers)


# ── RFC 9728 Protected Resource Metadata ───────────────────────────

@router.get(PRM_PATH)
@router.get(PRM_PATH + '/mcp')
@router.get(PRM_PATH + '/api/mcp')
async def oauth_protected_resource(request: Request):
    if not settings.oauth_enabled():
        return _not_found()
    suffix = request.url.path[len(PRM_PATH):]
    return _json(protected_resource_metadata(request, suffix or '/mcp'), headers=_doc_cache_headers())


# ── RFC 8414 Authorization Server Metadata ─────────────────────────

def authorization_server_metadata(request: Request) -> Dict:
    issuer = settings.public_base_url(request)
    doc = {
        'issuer': issuer,
        'authorization_endpoint': f'{issuer}/oauth/authorize',
        'token_endpoint': f'{issuer}/oauth/token',
        'jwks_uri': f'{issuer}/oauth/jwks',
        'response_types_supported': ['code'],
        'response_modes_supported': ['query'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'code_challenge_methods_supported': ['S256'],
        'token_endpoint_auth_methods_supported': ['none', 'client_secret_basic', 'client_secret_post'],
        'scopes_supported': asrv.supported_scopes(),
        'client_id_metadata_document_supported': settings.cimd_enabled(),
        'authorization_response_iss_parameter_supported': True,
    }
    if settings.dcr_enabled():
        doc['registration_endpoint'] = f'{issuer}/oauth/register'
    return doc


@router.get('/.well-known/oauth-authorization-server')
async def oauth_authorization_server(request: Request):
    if not _builtin_active():
        return _not_found()
    return _json(authorization_server_metadata(request), headers=_doc_cache_headers())


@router.get('/oauth/jwks')
async def oauth_jwks():
    if not _builtin_active():
        return _not_found()
    from sajha.auth.oauth.keys import get_signing_key
    return _json(get_signing_key().jwks(), headers={'Cache-Control': 'public, max-age=300'})


# ── /oauth/authorize ───────────────────────────────────────────────

def _page_headers() -> Dict[str, str]:
    # Clickjacking: the consent page must never be framed.  The security middleware keeps these.
    return {**_NO_STORE, 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
                                        "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                                        "font-src 'self'; frame-ancestors 'none'")}


def _error_page(request: Request, message: str, status: int = 400):
    """Errors that must NOT redirect (unknown client / redirect_uri mismatch: open-redirect guard)."""
    from sajha.app import render
    response = render(request, 'auth/oauth_consent.html',
                      {'session': {'token': ''}, 'fatal_error': message}, status_code=status)
    response.headers.update(_page_headers())
    return response


def _redirect_with(redirect_uri: str, params: Dict[str, str]) -> RedirectResponse:
    """Append params to the client's registered redirect URI (keeping its own query)."""
    p = urlsplit(redirect_uri)
    query = parse_qsl(p.query, keep_blank_values=True) + [(k, v) for k, v in params.items() if v is not None]
    target = urlunsplit((p.scheme, p.netloc, p.path, urlencode(query), ''))
    return RedirectResponse(target, status_code=302, headers=_NO_STORE)


def _error_redirect(redirect_uri: str, issuer: str, state: Optional[str], error: str, description: str):
    return _redirect_with(redirect_uri, {'error': error, 'error_description': description,
                                         'state': state, 'iss': issuer})


def _session_user(request: Request, db: Session):
    from sajha.auth import AuthManager
    token = request.cookies.get('sajha_token', '')
    return AuthManager.authenticate_jwt(db, token) if token else None


def _single(request: Request, name: str) -> Optional[str]:
    values = request.query_params.getlist(name)
    if len(values) > 1:
        raise ValueError(name)
    return values[0] if values else None


def _render_consent(request: Request, pending: asrv.PendingAuthorization, req_id: str, browser_token: str,
                    user, error: Optional[str] = None, status: int = 200):
    from sajha.app import render
    ctx = {
        'session': {'token': ''},
        'client_name': pending.client_name,
        'client_host': pending.client_host,
        'client_id': pending.client_id,
        'redirect_host': urlsplit(pending.redirect_uri).netloc or pending.redirect_uri,
        'scopes': [(s, _SCOPE_TEXT.get(s, s)) for s in pending.scopes],
        'req_id': req_id,
        'csrf': asrv.consent_csrf(req_id, browser_token),
        'user_name': (user.user_name or user.user_id) if user else None,
        'error': error,
    }
    response = render(request, 'auth/oauth_consent.html', ctx, status_code=status)
    response.headers.update(_page_headers())
    response.set_cookie(_TXN_COOKIE, browser_token, httponly=True, samesite='strict', path='/oauth',
                        secure=request.url.scheme == 'https', max_age=900)
    return response


@router.get('/oauth/authorize')
async def oauth_authorize(request: Request, db: Session = Depends(get_db)):
    if not _builtin_active():
        return _not_found()
    from sajha.security import check_api_rate_limit
    if not check_api_rate_limit(request):
        return _error_page(request, 'Too many requests. Try again shortly.', 429)
    try:
        client_id = _single(request, 'client_id')
        redirect_uri = _single(request, 'redirect_uri')
        state = _single(request, 'state')
    except ValueError as e:
        return _error_page(request, f'Duplicate {e} parameter.')

    # 1. Client and redirect URI first; until both check out, never redirect anywhere.
    try:
        client = await get_client_registry().resolve(client_id or '')
    except ClientError as e:
        return _error_page(request, f'Unknown or invalid client: {e}')
    if redirect_uri is None:
        if len(client.redirect_uris) != 1:
            return _error_page(request, 'redirect_uri is required for this client.')
        redirect_uri = client.redirect_uris[0]
    elif redirect_uri not in client.redirect_uris:          # exact string match
        return _error_page(request, 'redirect_uri does not match any URI registered for this client.')

    issuer = settings.public_base_url(request)
    q = request.query_params

    def fail(error: str, description: str):
        return _error_redirect(redirect_uri, issuer, state, error, description)

    try:
        for name in ('response_type', 'code_challenge', 'code_challenge_method', 'scope', 'resource', 'prompt'):
            _single(request, name)
    except ValueError as e:
        return fail('invalid_request' if str(e) != 'resource' else 'invalid_target', f'duplicate {e} parameter')
    if q.get('response_type') != 'code':
        return fail('unsupported_response_type', 'only response_type=code is supported')
    challenge = q.get('code_challenge')
    if not challenge:
        return fail('invalid_request', 'PKCE is required: send code_challenge with code_challenge_method=S256')
    if q.get('code_challenge_method') != 'S256':
        return fail('invalid_request', 'code_challenge_method must be S256')
    if not asrv.valid_code_challenge(challenge):
        return fail('invalid_request', 'malformed code_challenge')
    resource = q.get('resource')
    if resource is not None:
        resource = settings.canonical_resource(resource, request)
        if resource is None:
            return fail('invalid_target', 'resource is not an MCP endpoint of this server')
    resource = resource or settings.resource_uri(request)
    scopes = asrv.normalize_scope(q.get('scope'))

    user = _session_user(request, db)
    if q.get('prompt') == 'none':
        return fail('login_required' if not user else 'consent_required', 'interaction required')

    browser_token = request.cookies.get(_TXN_COOKIE) or secrets.token_urlsafe(24)
    pending = asrv.PendingAuthorization(
        client_id=client.client_id, client_name=client.name or client.client_id,
        client_host=client.display_host(), redirect_uri=redirect_uri, state=state,
        code_challenge=challenge, scopes=scopes, resource=resource, issuer=issuer,
        browser_hash=asrv.browser_hash(browser_token))
    try:
        req_id = asrv.get_store().add_pending(pending)
    except asrv.OAuthError as e:
        return fail(e.error, e.description)
    return _render_consent(request, pending, req_id, browser_token, user)


@router.post('/oauth/authorize')
async def oauth_authorize_decision(request: Request, db: Session = Depends(get_db)):
    if not _builtin_active():
        return _not_found()
    import hmac
    form = await request.form()
    req_id = str(form.get('req_id') or '')
    store = asrv.get_store()
    pending = store.get_pending(req_id)
    if pending is None:
        return _error_page(request, 'This authorization request has expired. Start again from your client.')

    # CSRF: the decision must come from the browser that loaded the consent page.
    browser_token = request.cookies.get(_TXN_COOKIE, '')
    if not browser_token or not hmac.compare_digest(asrv.browser_hash(browser_token), pending.browser_hash) \
            or not hmac.compare_digest(str(form.get('csrf') or ''), asrv.consent_csrf(req_id, browser_token)):
        return _error_page(request, 'Invalid or missing form token. Start again from your client.', 403)

    user = _session_user(request, db)
    decision = form.get('decision')
    if decision == 'approve' and user is None:
        from sajha.auth import AuthManager
        from sajha.security import check_auth_rate_limit, login_blocked, record_login_failure
        if not check_auth_rate_limit(request) or login_blocked(request):
            return _render_consent(request, pending, req_id, browser_token, None,
                                   'Too many sign-in attempts. Wait a minute and retry.', 429)
        login_id = str(form.get('user_id') or '')
        jwt_token, outcome = AuthManager.sign_in(db, login_id, str(form.get('password') or '')) \
            if login_id else (None, 'invalid')
        user = AuthManager.authenticate_jwt(db, jwt_token) if jwt_token else None
        if user is None:
            record_login_failure(request)
            return _render_consent(request, pending, req_id, browser_token, None,
                                   'Too many failed sign-ins for this account. Try again later.'
                                   if outcome == 'locked' else 'Invalid user ID or password.', 401)

    if store.pop_pending(req_id) is None:       # single use (double-submit race)
        return _error_page(request, 'This authorization request was already used.')
    if decision != 'approve':
        return _error_redirect(pending.redirect_uri, pending.issuer, pending.state,
                               'access_denied', 'the user denied the request')
    code = store.issue_code(pending, user.user_id)
    logger.info(f'OAuth code issued: user={user.user_id} client={pending.client_id} scopes={pending.scopes}')
    response = _redirect_with(pending.redirect_uri, {'code': code, 'state': pending.state, 'iss': pending.issuer})
    response.delete_cookie(_TXN_COOKIE, path='/oauth')
    return response


# ── /oauth/token ───────────────────────────────────────────────────

def _token_error(e: asrv.OAuthError, basic: bool = False) -> JSONResponse:
    headers = dict(_NO_STORE)
    if e.status == 401 and basic:
        headers['WWW-Authenticate'] = 'Basic realm="sajha-oauth"'
    return JSONResponse(e.body(), status_code=e.status, headers=headers)


def _authenticate_client(request: Request, form) -> OAuthClient:
    """Client authentication at the token endpoint (none | client_secret_basic | client_secret_post)."""
    header = request.headers.get('authorization', '')
    basic_id = basic_secret = None
    if header[:6].lower() == 'basic ':
        try:
            raw = base64.b64decode(header[6:].strip(), validate=True).decode('utf-8')
            cid, _, secret = raw.partition(':')
            basic_id, basic_secret = unquote(cid), unquote(secret)
        except (ValueError, UnicodeDecodeError):
            raise asrv.OAuthError('invalid_client', 'malformed Basic credentials', 401)
    form_id = form.get('client_id')
    if basic_id and form_id and form_id != basic_id:
        raise asrv.OAuthError('invalid_request', 'client_id mismatch')
    client_id = basic_id or form_id
    if not client_id:
        raise asrv.OAuthError('invalid_client', 'client authentication required', 401)
    secret = basic_secret if basic_id else form.get('client_secret')
    client = get_client_registry().local_client(client_id)
    if client is None and is_url_client_id(client_id) and settings.cimd_enabled():
        # CIMD clients are public; the code / refresh token is bound to this client_id.
        client = OAuthClient(client_id=client_id, redirect_uris=[], auth_method='none', source='cimd')
    if client is None:
        raise asrv.OAuthError('invalid_client', 'unknown client', 401)
    if client.is_public:
        if secret:
            raise asrv.OAuthError('invalid_client', 'public clients must not send a client secret', 401)
    elif not client.check_secret(secret):
        raise asrv.OAuthError('invalid_client', 'client authentication failed', 401)
    return client


@router.post('/oauth/token')
async def oauth_token(request: Request, db: Session = Depends(get_db)):
    if not _builtin_active():
        return _not_found()
    ctype = request.headers.get('content-type', '').split(';')[0].strip().lower()
    if ctype != 'application/x-www-form-urlencoded':
        return _token_error(asrv.OAuthError('invalid_request', 'use application/x-www-form-urlencoded'))
    form = await request.form()
    basic = request.headers.get('authorization', '')[:6].lower() == 'basic '
    try:
        client = _authenticate_client(request, form)
        grant = form.get('grant_type')
        if grant == 'authorization_code':
            body = _grant_code(request, form, client, db)
        elif grant == 'refresh_token':
            body = _grant_refresh(request, form, client, db)
        else:
            raise asrv.OAuthError('unsupported_grant_type', 'grant_type must be authorization_code or refresh_token')
    except asrv.OAuthError as e:
        return _token_error(e, basic)
    return JSONResponse(body, headers=_NO_STORE)


def _enabled_user(db: Session, user_id: str):
    from sajha.db.dao import UserDAO
    user = UserDAO(db).get_by_user_id(user_id)
    if user is None or not user.enabled:
        raise asrv.OAuthError('invalid_grant', 'the user account is no longer active')
    return user


def _grant_code(request: Request, form, client: OAuthClient, db: Session) -> Dict:
    store = asrv.get_store()
    rec = store.redeem_code(str(form.get('code') or ''))
    if rec.client_id != client.client_id:
        raise asrv.OAuthError('invalid_grant', 'code was issued to another client')
    if form.get('redirect_uri') != rec.redirect_uri:
        raise asrv.OAuthError('invalid_grant', 'redirect_uri does not match the authorization request')
    if not asrv.verify_pkce(form.get('code_verifier'), rec.code_challenge):
        raise asrv.OAuthError('invalid_grant', 'PKCE verification failed')
    resource = form.get('resource')
    if resource is not None and settings.canonical_resource(resource, request) != rec.resource:
        raise asrv.OAuthError('invalid_target', 'resource differs from the authorization request')
    if rec.issuer != settings.public_base_url(request):
        raise asrv.OAuthError('invalid_grant', 'code was issued by a different issuer')
    _enabled_user(db, rec.user_id)
    body = asrv.mint_access_token(rec.issuer, rec.user_id, client.client_id, rec.scopes, rec.resource)
    if asrv.wants_refresh(rec.scopes):
        rec.family = rec.family or uuid.uuid4().hex   # fixed atomically by redeem_code
        body['refresh_token'] = store.issue_refresh(rec.family, client.client_id, rec.user_id, rec.scopes,
                                                    rec.resource, rec.issuer)
    return body


def _grant_refresh(request: Request, form, client: OAuthClient, db: Session) -> Dict:
    store = asrv.get_store()
    rec = store.use_refresh(str(form.get('refresh_token') or ''), client.client_id)
    scopes = rec.scopes
    if form.get('scope'):
        asked = form.get('scope').split()
        if any(s not in rec.scopes for s in asked):
            raise asrv.OAuthError('invalid_scope', 'scope exceeds the original grant')
        scopes = [s for s in rec.scopes if s in asked]
    resource = form.get('resource')
    if resource is not None and settings.canonical_resource(resource, request) != rec.resource:
        raise asrv.OAuthError('invalid_target', 'resource differs from the original grant')
    if rec.issuer != settings.public_base_url(request):
        raise asrv.OAuthError('invalid_grant', 'refresh token was issued by a different issuer')
    _enabled_user(db, rec.user_id)
    body = asrv.mint_access_token(rec.issuer, rec.user_id, client.client_id, scopes, rec.resource)
    body['refresh_token'] = store.issue_refresh(rec.family, client.client_id, rec.user_id, scopes,
                                                rec.resource, rec.issuer, expires=rec.expires)
    return body


# ── RFC 7591 Dynamic Client Registration (deprecated; opt-in) ──────

@router.post('/oauth/register')
async def oauth_register(request: Request):
    if not (_builtin_active() and settings.dcr_enabled()):
        return _not_found()
    from sajha.security import check_auth_rate_limit
    if not check_auth_rate_limit(request):
        return JSONResponse({'error': 'temporarily_unavailable'}, status_code=429)
    try:
        metadata = json.loads(await request.body())
        info = get_client_registry().register(metadata)
    except ValueError:
        return JSONResponse({'error': 'invalid_client_metadata', 'error_description': 'body must be JSON'},
                            status_code=400, headers=_NO_STORE)
    except ClientError as e:
        error = 'invalid_redirect_uri' if 'redirect' in str(e) else 'invalid_client_metadata'
        return JSONResponse({'error': error, 'error_description': str(e)}, status_code=400, headers=_NO_STORE)
    return JSONResponse(info, status_code=201, headers=_NO_STORE)
