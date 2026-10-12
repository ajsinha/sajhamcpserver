"""
SAJHA MCP Server — the plugin catalog page and its endpoints (administrators).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

  GET  /admin/plugins/catalog                    the page (?review=<id> shows one review)
  POST /admin/plugins/catalog/review             form: source, ref -> a review (redirect)
  POST /admin/plugins/catalog/install            form: review, hash, approve, replace -> install (redirect)
  GET  /api/plugins/catalog                      every package of every source, with its signature verdict
  POST /api/plugins/catalog/review               JSON {source, ref} -> the review
  POST /api/plugins/catalog/install              JSON {review, hash, approve, replace?} -> the install
  GET  /api/plugins/catalog/reviews/{id}         one review

Session callers send the page's CSRF token (form field ``csrf`` or header ``X-CSRF-Token``).
The gate is the one of Describe a tool: sajha/core/plugin_catalog.py; design:
docs/security/Security Model.md, "Plugins".
"""

from __future__ import annotations

import logging
from typing import Any, Dict
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse

from sajha.app import render
from sajha.auth import AuthContext, require_admin
from sajha.routes.policy_routes import _csrf_ok, csrf_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=['plugins'])
PAGE = '/admin/plugins/catalog'


def _redirect(**q) -> RedirectResponse:
    return RedirectResponse(PAGE + ('?' + urlencode(q) if q else ''), status_code=303)


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def _run(fn, *args, **kwargs) -> JSONResponse:
    from sajha.core.plugin_catalog import CatalogError
    try:
        result = await run_in_threadpool(fn, *args, **kwargs)
    except CatalogError as e:
        return JSONResponse({'success': False, 'error': str(e), **e.extra}, status_code=e.status)
    except Exception as e:
        logger.error(f'plugin catalog failed: {e}', exc_info=True)
        return JSONResponse({'success': False, 'error': f'{e.__class__.__name__}: {e}'}, status_code=500)
    return JSONResponse({'success': True, **result})


def _truthy(v: Any) -> bool:
    return v is True or str(v).strip().lower() in ('1', 'true', 'yes', 'on')


@router.get(PAGE, name='admin_plugin_catalog_page')
async def admin_plugin_catalog_page(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.core import plugin_catalog as K
    qp = request.query_params
    listing = await run_in_threadpool(K.list_available)
    review, review_error = None, ''
    if qp.get('review'):
        try:
            review = K.get_draft(qp.get('review', '')[:32])
        except K.CatalogError as e:
            review_error = str(e)
    return render(request, 'admin/plugin_catalog.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': True, 'csrf': csrf_token(request, auth), 'listing': listing, 'review': review,
        'notice': qp.get('notice', '')[:300], 'error': (qp.get('error', '')[:500] or review_error)})


@router.post(PAGE + '/review')
async def admin_plugin_catalog_review(request: Request, auth: AuthContext = Depends(require_admin),
                                      csrf: str = Form(''), source: str = Form(''), ref: str = Form('')):
    from sajha.core import plugin_catalog as K
    if not _csrf_ok(request, auth, csrf):
        return _redirect(error='The form expired; reload the page and try again.')
    try:
        d = await run_in_threadpool(K.review, source, ref, auth)
    except K.CatalogError as e:
        return _redirect(error=str(e))
    return _redirect(review=d['id'])


@router.post(PAGE + '/install')
async def admin_plugin_catalog_install(request: Request, auth: AuthContext = Depends(require_admin),
                                       csrf: str = Form(''), review: str = Form(''), hash: str = Form(''),
                                       approve: str = Form(''), replace: str = Form('')):
    from sajha.core import plugin_catalog as K
    if not _csrf_ok(request, auth, csrf):
        return _redirect(error='The form expired; reload the page and try again.')
    try:
        r = await run_in_threadpool(K.install, review, hash, _truthy(approve), _truthy(replace), auth)
    except K.CatalogError as e:
        return _redirect(review=review, error=str(e))
    return _redirect(notice=r['message'])


def _api_csrf(request: Request, auth: AuthContext):
    if not _csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
        return JSONResponse({'success': False, 'error': 'missing or invalid X-CSRF-Token'}, status_code=403)
    return None


@router.get('/api/plugins/catalog')
async def api_plugin_catalog(auth: AuthContext = Depends(require_admin)):
    from sajha.core import plugin_catalog as K
    return await _run(K.list_available)


@router.post('/api/plugins/catalog/review')
async def api_plugin_catalog_review(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.core import plugin_catalog as K
    bad = _api_csrf(request, auth)
    if bad:
        return bad
    data = await _body(request)
    return await _run(K.review, str(data.get('source') or ''), str(data.get('ref') or ''), auth)


@router.post('/api/plugins/catalog/install')
async def api_plugin_catalog_install(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.core import plugin_catalog as K
    bad = _api_csrf(request, auth)
    if bad:
        return bad
    data = await _body(request)
    return await _run(K.install, str(data.get('review') or ''), str(data.get('hash') or ''),
                      _truthy(data.get('approve')), _truthy(data.get('replace')), auth)


@router.get('/api/plugins/catalog/reviews/{review_id}')
async def api_plugin_catalog_get(review_id: str, auth: AuthContext = Depends(require_admin)):
    from sajha.core import plugin_catalog as K
    return await _run(K.get_draft, review_id)
