"""
SAJHA MCP Server — Planner routing: proposals learned from results, approval, versions, rollback
and the online bandit's kill switch (administrators only).

  GET  /admin/planner-routing                         the page
  POST /admin/planner-routing/learn                   rank planners now and write a proposal
  POST /admin/planner-routing/{pid}/approve           {hash, approve} -> a new active version
  POST /admin/planner-routing/{pid}/reject            {reason}
  POST /admin/planner-routing/activate                {version} -> rollback (0: no rules)
  POST /admin/planner-routing/bandit                  {action: stop | resume | reset}
  GET  /api/ai/planner-routing                        settings, active version, versions, proposals, bandit
  GET  /api/ai/planner-routing/proposals/{pid}        one proposal (rules, evidence, diff, hash)
  POST /api/ai/planner-routing/{learn | proposals/{pid}/approve | proposals/{pid}/reject | activate | bandit}

Session callers send the page's CSRF token (form field ``csrf`` or header ``X-CSRF-Token``).
Design: docs/architecture/LLM Tools.md §9.13; files: docs/architecture/Planner Reference.md §6.6.2.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse

from sajha.app import render
from sajha.auth import AuthContext, require_admin
from sajha.routes.policy_routes import _csrf_ok, csrf_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=['planner-routing'])
PAGE = '/admin/planner-routing'


def _ts(t: Optional[float]) -> str:
    return datetime.fromtimestamp(float(t), timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if t else ''


def _redirect(**q) -> RedirectResponse:
    q = {k: v for k, v in q.items() if v}
    return RedirectResponse(PAGE + ('?' + urlencode(q) if q else ''), status_code=303)


def _context() -> Dict[str, Any]:
    from sajha.ai.planners_engine import learning as L
    st = L.status()
    for p in st['proposals']:
        p['when'] = _ts(p.get('created_at'))
    for v in st['versions']:
        v['when'] = _ts(v.get('approved_at'))
    for h in st['history']:
        h['when'] = _ts(h.get('at'))
    if st['bandit']['killed']:
        st['bandit']['killed']['when'] = _ts(st['bandit']['killed'].get('at'))
    return st


@router.get(PAGE, name='admin_planner_routing_page')
async def admin_planner_routing_page(request: Request, auth: AuthContext = Depends(require_admin)):
    qp = request.query_params
    ctx = await run_in_threadpool(_context)
    return render(request, 'admin/planner_routing.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles}, 'is_admin': True,
        'csrf': csrf_token(request, auth), 'st': ctx, 'open': qp.get('proposal', '')[:64],
        'notice': qp.get('notice', '')[:300], 'error': qp.get('error', '')[:300]})


# ── actions (shared by the form posts and the JSON API) ──────────

def _do(action: str, auth: AuthContext, data: Dict[str, Any]) -> Dict[str, Any]:
    from sajha.ai.planners_engine import learning as L
    uid = auth.user_id or ''
    if action == 'learn':
        doc = L.learn(created_by=uid, source='console')
        return {'notice': f"Proposal {doc['id']} written: {len(doc['diff'])} change(s) to review.",
                'proposal': doc['id'], 'doc': doc}
    if action == 'approve':
        if not data.get('approve'):
            raise L.RoutingError('approving needs explicit approval (approve) after you have reviewed the rules')
        doc = L.approve(str(data.get('pid') or ''), str(data.get('hash') or ''), auth, str(data.get('note') or ''))
        return {'notice': f"Approved: version {doc.get('version')} is active.", 'doc': doc}
    if action == 'reject':
        doc = L.reject(str(data.get('pid') or ''), uid, str(data.get('reason') or ''))
        return {'notice': f"Proposal {doc['id']} rejected.", 'doc': doc}
    if action == 'activate':
        try:
            n = int(data.get('version') or 0)
        except (TypeError, ValueError):
            raise L.RoutingError('version must be a number')
        doc = L.activate(n, uid, str(data.get('reason') or 'console'))
        return {'notice': f"Version {n} is active." if n else 'Routing rules are off (no version active).',
                'doc': doc}
    if action == 'bandit':
        b = L.get_bandit()
        what = str(data.get('action') or '')
        if what == 'stop':
            b.kill(uid, str(data.get('reason') or 'stopped on the console'))
            return {'notice': 'The bandit is stopped on every worker (kill switch set).'}
        if what == 'resume':
            b.resume(uid)
            return {'notice': 'The kill switch is cleared.'}
        if what == 'reset':
            return {'notice': f'Cleared {b.reset(uid)} bandit arm(s).'}
        raise L.RoutingError('action must be stop, resume or reset')
    raise L.RoutingError(f'unknown action {action}')


async def _form_action(request: Request, auth: AuthContext, csrf: str, act: str, **data) -> RedirectResponse:
    from sajha.ai.planners_engine.learning import RoutingError
    if not _csrf_ok(request, auth, csrf):
        return _redirect(error='The form expired; reload the page and try again.')
    try:
        out = await run_in_threadpool(_do, act, auth, data)
    except RoutingError as e:
        return _redirect(error=str(e), proposal=data.get('pid', ''))
    except Exception as e:
        logger.error(f'planner routing {act} failed: {e}', exc_info=True)
        return _redirect(error=f'{act} failed: {e}')
    return _redirect(notice=out['notice'], proposal=out.get('proposal', ''))


@router.post(PAGE + '/learn')
async def form_learn(request: Request, auth: AuthContext = Depends(require_admin), csrf: str = Form('')):
    return await _form_action(request, auth, csrf, 'learn')


@router.post(PAGE + '/activate')
async def form_activate(request: Request, auth: AuthContext = Depends(require_admin), csrf: str = Form(''),
                        version: str = Form('0'), reason: str = Form('')):
    return await _form_action(request, auth, csrf, 'activate', version=version, reason=reason[:300])


@router.post(PAGE + '/bandit')
async def form_bandit(request: Request, auth: AuthContext = Depends(require_admin), csrf: str = Form(''),
                      action: str = Form('')):
    return await _form_action(request, auth, csrf, 'bandit', action=action)


@router.post(PAGE + '/{pid}/approve')
async def form_approve(pid: str, request: Request, auth: AuthContext = Depends(require_admin), csrf: str = Form(''),
                       hash: str = Form(''), approve: str = Form(''), note: str = Form('')):
    return await _form_action(request, auth, csrf, 'approve', pid=pid, hash=hash, approve=bool(approve),
                              note=note[:500])


@router.post(PAGE + '/{pid}/reject')
async def form_reject(pid: str, request: Request, auth: AuthContext = Depends(require_admin), csrf: str = Form(''),
                      reason: str = Form('')):
    return await _form_action(request, auth, csrf, 'reject', pid=pid, reason=reason[:500])


# ── JSON API ─────────────────────────────────────────────────────

@router.get('/api/ai/planner-routing')
async def api_status(auth: AuthContext = Depends(require_admin)):
    from sajha.ai.planners_engine import learning as L
    return JSONResponse(await run_in_threadpool(L.status))


@router.get('/api/ai/planner-routing/proposals/{pid}')
async def api_proposal(pid: str, auth: AuthContext = Depends(require_admin)):
    from sajha.ai.planners_engine import learning as L
    try:
        return JSONResponse(await run_in_threadpool(L.get_store().proposal, pid))
    except L.RoutingError as e:
        return JSONResponse({'error': str(e)}, e.status)


async def _api(request: Request, auth: AuthContext, action: str, **extra) -> JSONResponse:
    from sajha.ai.planners_engine.learning import RoutingError
    if not _csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
        return JSONResponse({'error': 'missing or invalid X-CSRF-Token'}, 403)
    try:
        data = await request.json()
    except Exception:
        data = {}
    data = {**(data if isinstance(data, dict) else {}), **extra}
    try:
        out = await run_in_threadpool(_do, action, auth, data)
    except RoutingError as e:
        return JSONResponse({'error': str(e), **e.extra}, e.status)
    return JSONResponse({'success': True, **{k: v for k, v in out.items() if k != 'proposal'}})


@router.post('/api/ai/planner-routing/learn')
async def api_learn(request: Request, auth: AuthContext = Depends(require_admin)):
    return await _api(request, auth, 'learn')


@router.post('/api/ai/planner-routing/proposals/{pid}/approve')
async def api_approve(pid: str, request: Request, auth: AuthContext = Depends(require_admin)):
    return await _api(request, auth, 'approve', pid=pid)


@router.post('/api/ai/planner-routing/proposals/{pid}/reject')
async def api_reject(pid: str, request: Request, auth: AuthContext = Depends(require_admin)):
    return await _api(request, auth, 'reject', pid=pid)


@router.post('/api/ai/planner-routing/activate')
async def api_activate(request: Request, auth: AuthContext = Depends(require_admin)):
    return await _api(request, auth, 'activate')


@router.post('/api/ai/planner-routing/bandit')
async def api_bandit(request: Request, auth: AuthContext = Depends(require_admin)):
    return await _api(request, auth, 'bandit')
