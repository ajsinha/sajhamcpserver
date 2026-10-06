"""
SAJHA MCP Server — Policies, Approvals and Audit: the admin pages and their JSON API (admin only).

* ``/admin/policies``: every policy file, its rules and parse errors; the test bench
  ("would this call be allowed?") evaluates a call without running it or touching counters.
* ``/admin/approvals``: pending tool-call approvals with Approve and Deny; recent decisions.
* ``/admin/audit``: the hash chains' integrity (Verify), recent records merged across
  chains, the SIEM sinks; Anchor now.

Session callers send the page's CSRF token (form field ``csrf`` or header ``X-CSRF-Token``);
API-key and bearer callers need none. Design: docs/architecture/Policy and Audit.md, section 9.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse

from sajha.app import render
from sajha.auth import AuthContext, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(tags=['policy-audit'])


# ── CSRF ────────────────────────────────────────────────────────────

def _csrf_key() -> bytes:
    from sajha.core.config import get_settings
    return hashlib.sha256(b'sajha-policy-csrf|' + get_settings().secret_key.encode()).digest()


def csrf_token(request: Request, auth: AuthContext) -> str:
    binding = hashlib.sha256(request.cookies.get('sajha_token', '').encode()).hexdigest()
    return hmac.new(_csrf_key(), f'{auth.user_id}|{binding}'.encode(), hashlib.sha256).hexdigest()


def _cookie_auth(request: Request) -> bool:
    return bool(request.cookies.get('sajha_token')) and not (
        request.headers.get('Authorization') or request.headers.get('X-API-Key'))


def _csrf_ok(request: Request, auth: AuthContext, given: Optional[str]) -> bool:
    if not _cookie_auth(request):
        return True
    return bool(given) and hmac.compare_digest(str(given), csrf_token(request, auth))


def _user(auth: AuthContext) -> Dict[str, Any]:
    return {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles}


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _engine():
    from sajha.policy.engine import get_engine
    return get_engine()


def _ts(t: Optional[float]) -> str:
    if not t:
        return ''
    return datetime.fromtimestamp(float(t), timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


# ── Policies ────────────────────────────────────────────────────────

def _policies_summary() -> Dict[str, Any]:
    from sajha.core.config import _get
    from sajha.policy.engine import default_effect, enabled
    eng = _engine()
    pols = eng.policy_set.policies()
    return {'enabled': enabled(), 'default_effect': default_effect(), 'directory': eng.policy_set.directory,
            'on_error': (_get('policy.on_error', 'ignore') or 'ignore'),
            'loaded_at': _ts(eng.policy_set.loaded_at), 'active': eng.active(),
            'enforced_rules': len(eng.rules()), 'policies': [p.summary() for p in pols]}


@router.get('/admin/policies', name='admin_policies_page')
async def admin_policies_page(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.policy.context import SOURCES
    from sajha.app import tools_registry
    summary = await run_in_threadpool(_policies_summary)
    tools = sorted(tools_registry.tools.keys()) if tools_registry else []
    return render(request, 'admin/policies.html', {
        'user': _user(auth), 'is_admin': True, 'csrf': csrf_token(request, auth), 'summary': summary,
        'sources': SOURCES, 'tool_names': tools})


@router.get('/api/policy/policies')
async def api_policies(auth: AuthContext = Depends(require_admin)):
    return await run_in_threadpool(_policies_summary)


@router.post('/api/policy/reload')
async def api_policy_reload(request: Request, auth: AuthContext = Depends(require_admin)):
    if not _csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
        return JSONResponse({'error': 'missing or invalid CSRF token'}, status_code=403)
    changed = await run_in_threadpool(_engine().policy_set.refresh, True)
    _audit_admin(auth, 'policy.reload', {'changed': changed})
    return await run_in_threadpool(_policies_summary)


def bench_call(data: Dict[str, Any]) -> Dict[str, Any]:
    """The test bench: evaluate a described call; nothing runs, no counter moves."""
    from sajha.observability.caller import Caller
    from sajha.policy.engine import Call
    from sajha.policy import redact as R
    from sajha.app import tools_registry
    tool = str(data.get('tool') or '').strip()
    if not tool:
        raise ValueError('tool is required')
    args = data.get('arguments') or {}
    if isinstance(args, str):
        args = json.loads(args) if args.strip() else {}
    if not isinstance(args, dict):
        raise ValueError('arguments must be a JSON object')
    anonymous = bool(data.get('anonymous'))
    roles = data.get('roles') or []
    if isinstance(roles, str):
        roles = [r.strip() for r in roles.split(',') if r.strip()]
    caller = Caller('anonymous', '', (), '') if anonymous else Caller(
        str(data.get('user') or 'admin'), str(data.get('api_key') or ''), tuple(roles), str(data.get('auth_type') or ''))
    when = data.get('time')
    now = datetime.now(timezone.utc)
    if when:
        now = datetime.fromisoformat(str(when).replace('Z', '+00:00'))
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    t = tools_registry.get_tool(tool) if tools_registry else None
    cfg = getattr(t, 'config', None) or {}
    ann = cfg.get('annotations') if isinstance(cfg.get('annotations'), dict) else {}
    call = Call(tool, args, caller, str(data.get('source') or 'rest'), ann, now)
    d = _engine().evaluate(call, include_disabled=bool(data.get('include_disabled')))
    out = {'decision': d.to_dict(), 'tool_known': t is not None, 'annotations': ann,
           'would_run': d.effect == 'allow', 'evaluated_at': now.isoformat()}
    sample = data.get('output')
    if isinstance(sample, str) and sample:
        preview = sample
        found = 0
        if d.screen:
            preview, found = R.screen(sample, d.screen)
        if d.redact:
            preview, counts = R.redact(preview, d.redact)
        else:
            counts = {}
        out['output'] = {'result': preview, 'redactions': counts, 'injection_markers': found,
                         'blocked': bool(found and d.screen == 'block')}
    return out


@router.post('/api/policy/test')
async def api_policy_test(request: Request, auth: AuthContext = Depends(require_admin)):
    data = await _body(request)
    try:
        return await run_in_threadpool(bench_call, data)
    except (ValueError, TypeError) as e:
        return JSONResponse({'error': str(e)}, status_code=400)


# ── Approvals ───────────────────────────────────────────────────────

def _approval_rows(status: Optional[str] = None):
    from sajha.policy import approvals
    rows = approvals.list_all(status)
    for r in rows:
        r['created'] = _ts(r.get('created_at'))
        r['decided'] = _ts(r.get('decided_at'))
        r['expires'] = _ts(r.get('expires_at'))
        r['arguments_json'] = json.dumps(r.get('arguments'), indent=2, default=str)[:4000]
    return rows


@router.get('/admin/approvals', name='admin_approvals_page')
async def admin_approvals_page(request: Request, auth: AuthContext = Depends(require_admin)):
    rows = await run_in_threadpool(_approval_rows)
    from sajha.core.state import get_state_store
    return render(request, 'admin/approvals.html', {
        'user': _user(auth), 'is_admin': True, 'csrf': csrf_token(request, auth),
        'pending': [r for r in rows if r.get('status') == 'pending'],
        'decided': [r for r in rows if r.get('status') != 'pending'][:100],
        'notice': request.query_params.get('notice', '')[:300], 'error': request.query_params.get('error', '')[:300],
        'store_shared': get_state_store().shared})


@router.post('/admin/approvals/{aid}/decide')
async def admin_approval_decide(aid: str, request: Request, auth: AuthContext = Depends(require_admin),
                                csrf: str = Form(''), decision: str = Form(''), note: str = Form('')):
    if not _csrf_ok(request, auth, csrf):
        return RedirectResponse('/admin/approvals?' + urlencode(
            {'error': 'The form expired; reload the page and try again.'}), status_code=303)
    from sajha.policy import approvals
    try:
        rec = await run_in_threadpool(approvals.decide, aid, decision == 'approve', auth.user_id, note)
    except approvals.ApprovalError as e:
        return RedirectResponse('/admin/approvals?' + urlencode({'error': str(e)}), status_code=303)
    msg = f"{'Approved' if rec['status'] == 'approved' else 'Denied'} {rec['tool']} for {rec['caller']['user_id']}."
    return RedirectResponse('/admin/approvals?' + urlencode({'notice': msg}), status_code=303)


@router.get('/api/policy/approvals')
async def api_approvals(request: Request, auth: AuthContext = Depends(require_admin)):
    status = request.query_params.get('status') or None
    return {'approvals': await run_in_threadpool(_approval_rows, status)}


async def _decide_api(aid: str, approve: bool, request: Request, auth: AuthContext):
    if not _csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
        return JSONResponse({'error': 'missing or invalid CSRF token'}, status_code=403)
    from sajha.policy import approvals
    data = await _body(request)
    try:
        rec = await run_in_threadpool(approvals.decide, aid, approve, auth.user_id, str(data.get('note') or ''))
    except approvals.ApprovalError as e:
        return JSONResponse({'error': str(e)}, status_code=409)
    return {'approval': rec}


@router.post('/api/policy/approvals/{aid}/approve')
async def api_approval_approve(aid: str, request: Request, auth: AuthContext = Depends(require_admin)):
    return await _decide_api(aid, True, request, auth)


@router.post('/api/policy/approvals/{aid}/deny')
async def api_approval_deny(aid: str, request: Request, auth: AuthContext = Depends(require_admin)):
    return await _decide_api(aid, False, request, auth)


# ── Audit ───────────────────────────────────────────────────────────

def _db_engine():
    from sajha.db.engine import get_engine
    return get_engine()


def _records(limit: int = 100, event: Optional[str] = None, actor: Optional[str] = None,
             chain: Optional[str] = None):
    from sajha.audit import get_writer
    from sajha.audit.chain import recent
    try:
        get_writer().flush()
    except Exception:
        pass
    from sqlalchemy import inspect
    eng = _db_engine()
    if not inspect(eng).has_table('audit_chain'):
        return []
    return recent(eng, limit=limit, event=event, actor=actor, chain_id=chain)


def _verify(chain: Optional[str] = None):
    from sajha.audit import get_writer
    from sajha.audit.verify import verify
    try:
        get_writer().flush()
    except Exception:
        pass
    return verify(_db_engine(), chain_id=chain)


@router.get('/admin/audit', name='admin_audit_page')
async def admin_audit_page(request: Request, auth: AuthContext = Depends(require_admin)):
    import sajha.audit as A
    q = request.query_params
    error = ''
    try:
        records = await run_in_threadpool(_records, 100, q.get('event') or None, q.get('actor') or None)
    except Exception as e:
        records, error = [], f'cannot read the audit chain: {e}'
    for r in records:
        r['details_json'] = json.dumps(r.get('details'), default=str)[:600] if r.get('details') is not None else ''
    return render(request, 'admin/audit.html', {
        'user': _user(auth), 'is_admin': True, 'csrf': csrf_token(request, auth), 'records': records,
        'status': A.status(), 'filter_event': q.get('event', ''), 'filter_actor': q.get('actor', ''),
        'error': error})


@router.get('/api/audit/records')
async def api_audit_records(request: Request, auth: AuthContext = Depends(require_admin)):
    q = request.query_params
    try:
        limit = int(q.get('limit') or 100)
    except ValueError:
        limit = 100
    return {'records': await run_in_threadpool(_records, limit, q.get('event') or None, q.get('actor') or None,
                                               q.get('chain') or None)}


@router.get('/api/audit/verify')
async def api_audit_verify(request: Request, auth: AuthContext = Depends(require_admin)):
    return await run_in_threadpool(_verify, request.query_params.get('chain') or None)


@router.post('/api/audit/anchor')
async def api_audit_anchor(request: Request, auth: AuthContext = Depends(require_admin)):
    if not _csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
        return JSONResponse({'error': 'missing or invalid CSRF token'}, status_code=403)
    from sajha.audit import get_writer
    w = get_writer()
    a = await run_in_threadpool(w.anchor)
    return {'anchored': a is not None, 'anchor': a['payload'] if a else None, 'writer': w.status()}


@router.get('/api/audit/sinks')
async def api_audit_sinks(auth: AuthContext = Depends(require_admin)):
    import sajha.audit as A
    return A.status()


def _audit_admin(auth: AuthContext, what: str, details: Any = None) -> None:
    try:
        from sajha.core.audit import AuditLogger
        AuditLogger().config_changed(what, by_user=auth.user_id,
                                     details=json.dumps(details, default=str)[:2000] if details else None)
    except Exception as e:
        logger.debug(f'policy admin audit: {e}')
