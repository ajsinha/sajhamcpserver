"""
SAJHA MCP Server — Tool quality pages and their JSON API (administrators only).

* ``/admin/tool-health``: health probes (state, history, run now), saved test runs (run the
  harness), and the schema linter.
* ``/admin/evals``: eval sets, start a run (model, planner) in the background, recent runs, a
  run's questions, and the comparison of two runs.
* ``/admin/tool-versions``: versioned tools, their routing, per-version window statistics and
  rollbacks; edit the versions file, set the canary, promote, clear a rollback.

Session callers send the page's CSRF token (form field ``csrf`` or header ``X-CSRF-Token``);
API-key and bearer callers need none. Design: docs/architecture/Tool Quality.md §8.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse

from sajha.app import render
from sajha.auth import AuthContext, require_admin
from sajha.routes.policy_routes import _csrf_ok, csrf_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=['quality'])


def _user(auth: AuthContext) -> Dict[str, Any]:
    return {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles}


def _registry():
    from sajha.app import tools_registry
    return tools_registry


def _ts(t: Optional[float]) -> str:
    if not t:
        return ''
    return datetime.fromtimestamp(float(t), timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def _redirect(path: str, **q) -> RedirectResponse:
    q = {k: v for k, v in q.items() if v}
    return RedirectResponse(path + ('?' + urlencode(q) if q else ''), status_code=303)


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _api_csrf(request: Request, auth: AuthContext) -> Optional[JSONResponse]:
    if not _csrf_ok(request, auth, request.headers.get('X-CSRF-Token')):
        return JSONResponse({'error': 'missing or invalid X-CSRF-Token'}, 403)
    return None


def _runs(kind: str, limit: int = 30) -> List[Dict[str, Any]]:
    from sajha.quality.store import get_run_store
    try:
        rows = get_run_store().list(kind, limit)
    except Exception as e:
        logger.warning(f'quality runs unavailable: {e}')
        return []
    for r in rows:
        r['started'] = _ts(r['started_at'])
    return rows


# ── Tool Health ─────────────────────────────────────────────────────

def _health_context(lint: bool, level: str, run_id: str) -> Dict[str, Any]:
    from sajha.quality import cases as C, lint as L, probes as P
    reg = _registry()
    suite = C.load_suite(registry=reg)
    probes = P.overview(reg, suite)
    for p in probes:
        p['next_text'] = _ts(p.get('next'))
        if p.get('last'):
            p['last']['when'] = _ts(p['last'].get('at'))
        for h in p.get('history') or []:
            h['when'] = _ts(h.get('at'))
    ctx: Dict[str, Any] = {'probes': probes, 'probes_enabled': P.enabled(), 'suite_errors': suite.errors,
                           'case_count': len(suite.cases), 'tool_count': len(suite.tools()),
                           'test_runs': _runs('test', 20), 'lint': None, 'level': level, 'run': None}
    if run_id:
        from sajha.quality.store import get_run_store
        try:
            ctx['run'] = get_run_store().get(run_id)
        except Exception:
            ctx['run'] = None
    if lint:
        findings = L.lint_registry(reg, '', suite)
        shown = [f.to_dict() for f in findings if not level or f.level == level]
        ctx['lint'] = {'summary': L.summarise(findings), 'tools': len(getattr(reg, 'tools', {}) or {}),
                       'findings': shown[:1000], 'truncated': len(shown) > 1000}
    return ctx


@router.get('/admin/tool-health', name='admin_tool_health_page')
async def admin_tool_health_page(request: Request, auth: AuthContext = Depends(require_admin)):
    qp = request.query_params
    level = qp.get('level', '') if qp.get('level', '') in ('', 'error', 'warning', 'info') else ''
    ctx = await run_in_threadpool(_health_context, qp.get('lint') == '1', level, qp.get('run', '')[:64])
    return render(request, 'admin/tool_health.html', {
        'user': _user(auth), 'is_admin': True, 'csrf': csrf_token(request, auth), **ctx,
        'notice': qp.get('notice', '')[:300], 'error': qp.get('error', '')[:300]})


@router.post('/admin/tool-health/probes/{tool}/run')
async def admin_probe_run(tool: str, request: Request, auth: AuthContext = Depends(require_admin), csrf: str = Form('')):
    if not _csrf_ok(request, auth, csrf):
        return _redirect('/admin/tool-health', error='The form expired; reload the page and try again.')
    try:
        entry = await run_in_threadpool(_run_probe, tool, f'admin:{auth.user_id}')
    except LookupError as e:
        return _redirect('/admin/tool-health', error=str(e))
    return _redirect('/admin/tool-health', notice=f'Probe {tool}: {entry["status"]} in {entry["duration_ms"]:.0f} ms.')


def _run_probe(tool: str, trigger: str) -> Dict[str, Any]:
    from sajha.quality import cases as C, probes as P
    reg = _registry()
    suite = C.load_suite(registry=reg)
    spec = suite.probes.get(tool)
    if spec is None:
        raise LookupError(f'{tool} has no probe')
    return P.run_probe(reg, spec, suite, trigger=trigger)


def _run_tests(tool_glob: str, mode: str, user: str) -> Dict[str, Any]:
    from sajha.quality import cases as C, runner as R
    from sajha.quality.store import get_run_store
    reg = _registry()
    suite = C.load_suite(registry=reg)
    selected = C.select(suite.cases, tool_glob)
    results = R.run_cases(reg, selected, mode)
    summary = {**R.summarise(results), 'mode': mode, 'tool_glob': tool_glob or '*'}
    rid = get_run_store().save('test', f'{tool_glob or "all tools"} ({mode})', summary,
                               [r.to_dict() for r in results], created_by=user)
    return {'id': rid, 'summary': summary, 'results': [r.to_dict() for r in results]}


@router.post('/admin/tool-health/tests/run')
async def admin_tests_run(request: Request, auth: AuthContext = Depends(require_admin), csrf: str = Form(''),
                          tool: str = Form(''), mode: str = Form('replay')):
    if not _csrf_ok(request, auth, csrf):
        return _redirect('/admin/tool-health', error='The form expired; reload the page and try again.')
    if mode not in ('auto', 'replay', 'live'):
        mode = 'replay'
    try:
        out = await run_in_threadpool(_run_tests, tool.strip()[:200], mode, auth.user_id)
    except Exception as e:
        return _redirect('/admin/tool-health', error=f'Test run failed: {e}')
    s = out['summary']
    return _redirect('/admin/tool-health', run=out['id'],
                     notice=f'{s["total"]} cases: {s["pass"]} passed, {s["fail"]} failed, {s["error"]} errors.')


@router.get('/api/quality/probes')
async def api_probes(auth: AuthContext = Depends(require_admin)):
    from sajha.quality import probes as P
    return JSONResponse({'enabled': P.enabled(), 'probes': await run_in_threadpool(P.overview, _registry())})


@router.post('/api/quality/probes/{tool}/run')
async def api_probe_run(tool: str, request: Request, auth: AuthContext = Depends(require_admin)):
    bad = _api_csrf(request, auth)
    if bad:
        return bad
    try:
        return JSONResponse(await run_in_threadpool(_run_probe, tool, f'api:{auth.user_id}'))
    except LookupError as e:
        return JSONResponse({'error': str(e)}, 404)


@router.get('/api/quality/lint')
async def api_lint(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.quality import cases as C, lint as L

    def work():
        reg = _registry()
        findings = L.lint_registry(reg, request.query_params.get('tool', ''), C.load_suite(registry=reg))
        return {'summary': L.summarise(findings), 'findings': [f.to_dict() for f in findings]}
    return JSONResponse(await run_in_threadpool(work))


@router.post('/api/quality/tests/run')
async def api_tests_run(request: Request, auth: AuthContext = Depends(require_admin)):
    bad = _api_csrf(request, auth)
    if bad:
        return bad
    data = await _body(request)
    mode = data.get('mode', 'replay')
    if mode not in ('auto', 'replay', 'live'):
        return JSONResponse({'error': 'mode must be auto, replay or live'}, 400)
    return JSONResponse(await run_in_threadpool(_run_tests, str(data.get('tool', ''))[:200], mode, auth.user_id))


@router.get('/api/quality/runs')
async def api_runs(request: Request, auth: AuthContext = Depends(require_admin)):
    kind = request.query_params.get('kind') or None
    if kind not in (None, 'test', 'eval'):
        return JSONResponse({'error': 'kind must be test or eval'}, 400)
    return JSONResponse({'runs': await run_in_threadpool(_runs, kind, 100)})


@router.get('/api/quality/runs/{rid}')
async def api_run(rid: str, auth: AuthContext = Depends(require_admin)):
    from sajha.quality.store import get_run_store
    row = await run_in_threadpool(get_run_store().get, rid)
    return JSONResponse(row) if row else JSONResponse({'error': 'Not found'}, 404)


# ── Evals ───────────────────────────────────────────────────────────

def _service():
    from sajha.ai.intelligence import get_intelligence
    return get_intelligence()


def _models() -> List[str]:
    try:
        from sajha.ai.llm import llm_factory
        gw = llm_factory()
        out = [m.qualified_id for m in gw.models() if m.kind != 'embedding']
        return sorted(set(out)) + sorted(a for a in (gw.settings.aliases or {}) if a != 'embedding')
    except Exception:
        return []


def _planners() -> List[str]:
    try:
        from sajha.ai.planners_engine import get_registry
        return get_registry().names()
    except Exception:
        return []


def _evals_context(run_id: str, a: str, b: str) -> Dict[str, Any]:
    from sajha.quality import evals as E
    sets = E.load_sets()
    runs = _runs('eval', 50)
    ctx: Dict[str, Any] = {'sets': [s.to_dict() for s in sets.values()], 'runs': runs, 'models': _models(),
                           'planners': _planners(), 'run': None, 'compare': None,
                           'running': any(r['status'] == 'running' for r in runs), 'ask_ready': _service() is not None}
    if run_id:
        ctx['run'] = E.saved_run(run_id)
        if ctx['run'] is not None:
            ctx['run']['id'] = run_id
    if a and b:
        ra, rb = E.saved_run(a), E.saved_run(b)
        if ra and rb:
            ctx['compare'] = E.compare(ra, rb)
    return ctx


@router.get('/admin/evals', name='admin_evals_page')
async def admin_evals_page(request: Request, auth: AuthContext = Depends(require_admin)):
    qp = request.query_params
    ctx = await run_in_threadpool(_evals_context, qp.get('run', '')[:64], qp.get('a', '')[:64], qp.get('b', '')[:64])
    return render(request, 'admin/evals.html', {
        'user': _user(auth), 'is_admin': True, 'csrf': csrf_token(request, auth), **ctx,
        'sel_a': qp.get('a', ''), 'sel_b': qp.get('b', ''),
        'notice': qp.get('notice', '')[:300], 'error': qp.get('error', '')[:300]})


def _start_eval(auth: AuthContext, set_name: str, model: str, planner: str) -> str:
    from sajha.ai.llm import RequestContext
    from sajha.quality import evals as E
    sets = E.load_sets()
    es = sets.get(set_name)
    if es is None:
        raise LookupError(f'no eval set {set_name!r}')
    svc = _service()
    if svc is None:
        raise LookupError('Ask SAJHA is not available (no intelligence service)')
    if planner and planner not in _planners():
        raise LookupError(f'unknown planner {planner!r}')
    model = model or (es.models[0] if es.models else '')
    planner = planner or (es.planners[0] if es.planners else '')
    ctx = RequestContext(user_id=auth.user_id, roles=list(auth.roles or []), is_admin=True,
                         can_use_tool=lambda name: auth.has_tool_access(name))
    return E.start_background(svc, es, model, planner, auth.user_id, ctx)


@router.post('/admin/evals/run')
async def admin_evals_run(request: Request, auth: AuthContext = Depends(require_admin), csrf: str = Form(''),
                          set_name: str = Form(''), model: str = Form(''), planner: str = Form('')):
    if not _csrf_ok(request, auth, csrf):
        return _redirect('/admin/evals', error='The form expired; reload the page and try again.')
    try:
        rid = await run_in_threadpool(_start_eval, auth, set_name, model.strip()[:200], planner.strip()[:100])
    except Exception as e:
        return _redirect('/admin/evals', error=str(e))
    return _redirect('/admin/evals', run=rid, notice='Eval run started; this page refreshes until it finishes.')


@router.get('/api/quality/evals')
async def api_evals(auth: AuthContext = Depends(require_admin)):
    from sajha.quality import evals as E
    return JSONResponse({'sets': [s.to_dict() for s in E.load_sets().values()], 'runs': _runs('eval', 50)})


@router.post('/api/quality/evals/run')
async def api_evals_run(request: Request, auth: AuthContext = Depends(require_admin)):
    bad = _api_csrf(request, auth)
    if bad:
        return bad
    data = await _body(request)
    try:
        rid = await run_in_threadpool(_start_eval, auth, str(data.get('set', '')), str(data.get('model', ''))[:200],
                                      str(data.get('planner', ''))[:100])
    except LookupError as e:
        return JSONResponse({'error': str(e)}, 400)
    return JSONResponse({'id': rid, 'status': 'running'}, 202)


@router.get('/api/quality/evals/compare')
async def api_evals_compare(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.quality import evals as E
    a, b = request.query_params.get('a', ''), request.query_params.get('b', '')
    ra, rb = await run_in_threadpool(E.saved_run, a), await run_in_threadpool(E.saved_run, b)
    if not ra or not rb:
        return JSONResponse({'error': 'a and b must be finished eval run ids'}, 404)
    return JSONResponse(E.compare(ra, rb))


# ── Tool Versions ───────────────────────────────────────────────────

_TEMPLATE = """tool: {tool}
versions:
  "{next}":
    overrides:
      description: {desc}
routing:
  canary: {{version: "{next}", percent: 0}}
rollback:
  max_error_rate: 0.2
  min_calls: 20
  window_seconds: 300
"""


def _versions_context(selected: str) -> Dict[str, Any]:
    from pathlib import Path
    from sajha.quality import versions as V
    m = V.get_manager()
    reg = _registry()
    tools = []
    for name, vf in sorted(m.files().items()):
        tool = reg.get_tool(name) if reg else None
        if tool is None:
            tools.append({'tool': name, 'missing': True, 'source': vf.source})
            continue
        d = m.describe(tool)
        try:
            d['text'] = Path(vf.source).read_text(encoding='utf-8')
        except OSError:
            d['text'] = ''
        for v in d['versions']:
            if v.get('rolled_back'):
                v['rolled_back']['when'] = _ts(v['rolled_back'].get('at'))
        tools.append(d)
    template = ''
    if selected and reg and reg.get_tool(selected) and selected not in m.files():
        t = reg.get_tool(selected)
        template = _TEMPLATE.format(tool=selected, next='2.0.0' if str(t.version) != '2.0.0' else '3.0.0',
                                    desc=(str(t.description or '').replace('\n', ' ')[:120] or 'TODO').replace(':', ' -'))
    return {'tools': tools, 'errors': m.errors(), 'enabled': V.enabled(), 'directory': str(m.directory),
            'tool_names': sorted(getattr(reg, 'tools', {}) or {}), 'selected': selected, 'template': template}


@router.get('/admin/tool-versions', name='admin_tool_versions_page')
async def admin_tool_versions_page(request: Request, auth: AuthContext = Depends(require_admin)):
    qp = request.query_params
    ctx = await run_in_threadpool(_versions_context, qp.get('new', '')[:128])
    return render(request, 'admin/tool_versions.html', {
        'user': _user(auth), 'is_admin': True, 'csrf': csrf_token(request, auth), **ctx,
        'notice': qp.get('notice', '')[:300], 'error': qp.get('error', '')[:300]})


def _tool_or_error(name: str):
    reg = _registry()
    tool = reg.get_tool(name) if reg else None
    if tool is None:
        raise LookupError(f'Tool not found: {name}')
    return tool


def _do(action: str, tool_name: str, user: str, **kw) -> str:
    from sajha.quality import versions as V
    tool = _tool_or_error(tool_name)
    m = V.get_manager()
    base = str(tool.version)
    if action == 'save':
        m.save_text(tool_name, kw['text'], base)
        msg = f'Saved the versions file of {tool_name}.'
    elif action == 'canary':
        try:
            pct = float(kw['percent'])
        except (TypeError, ValueError):
            raise V.VersionsError('percent must be a number')
        m.set_canary(tool_name, kw['version'], pct, base)
        msg = f'{tool_name}: canary {kw["version"]} at {pct:g}%.'
    elif action == 'promote':
        m.promote(tool_name, kw['version'], base)
        msg = f'{tool_name}: {kw["version"]} is now stable.'
    elif action == 'clear':
        m.clear_rollback(tool_name, kw['version'], user)
        msg = f'{tool_name}: rollback of {kw["version"]} cleared.'
    else:
        raise ValueError(action)
    try:
        from sajha import audit
        audit.record(f'quality.versions.{action}', actor={'user': user}, resource={'tool': tool_name},
                     outcome='ok', details={k: v for k, v in kw.items() if k != 'text'})
    except Exception:
        pass
    return msg


@router.post('/admin/tool-versions/{tool}/{action}')
async def admin_tool_versions_action(tool: str, action: str, request: Request, auth: AuthContext = Depends(require_admin),
                                     csrf: str = Form(''), text: str = Form(''), version: str = Form(''),
                                     percent: str = Form('0')):
    if not _csrf_ok(request, auth, csrf):
        return _redirect('/admin/tool-versions', error='The form expired; reload the page and try again.')
    if action not in ('save', 'canary', 'promote', 'clear'):
        return _redirect('/admin/tool-versions', error=f'unknown action {action}')
    try:
        msg = await run_in_threadpool(_do, action, tool, auth.user_id, text=text, version=version.strip(),
                                      percent=percent)
    except Exception as e:
        back = {'new': tool} if action == 'save' else {}
        return _redirect('/admin/tool-versions', error=f'{tool}: {e}', **back)
    return _redirect('/admin/tool-versions', notice=msg)


@router.get('/api/quality/versions')
async def api_versions(auth: AuthContext = Depends(require_admin)):
    ctx = await run_in_threadpool(_versions_context, '')
    return JSONResponse({'enabled': ctx['enabled'], 'directory': ctx['directory'], 'errors': ctx['errors'],
                         'tools': [{k: v for k, v in t.items() if k != 'text'} for t in ctx['tools']]})


@router.put('/api/quality/versions/{tool}')
async def api_versions_put(tool: str, request: Request, auth: AuthContext = Depends(require_admin)):
    bad = _api_csrf(request, auth)
    if bad:
        return bad
    text = (await request.body()).decode('utf-8', 'replace')
    try:
        msg = await run_in_threadpool(_do, 'save', tool, auth.user_id, text=text)
    except LookupError as e:
        return JSONResponse({'error': str(e)}, 404)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, 400)
    return JSONResponse({'success': True, 'message': msg})


async def _api_action(action: str, tool: str, request: Request, auth: AuthContext, version: str = '', percent: Any = 0):
    bad = _api_csrf(request, auth)
    if bad:
        return bad
    try:
        msg = await run_in_threadpool(_do, action, tool, auth.user_id, version=version, percent=percent)
    except LookupError as e:
        return JSONResponse({'error': str(e)}, 404)
    except ValueError as e:
        return JSONResponse({'error': str(e)}, 400)
    return JSONResponse({'success': True, 'message': msg})


@router.post('/api/quality/versions/{tool}/canary')
async def api_versions_canary(tool: str, request: Request, auth: AuthContext = Depends(require_admin)):
    data = await _body(request)
    return await _api_action('canary', tool, request, auth, str(data.get('version', '')), data.get('percent', 0))


@router.post('/api/quality/versions/{tool}/promote')
async def api_versions_promote(tool: str, request: Request, auth: AuthContext = Depends(require_admin)):
    data = await _body(request)
    return await _api_action('promote', tool, request, auth, str(data.get('version', '')))


@router.delete('/api/quality/versions/{tool}/rollback/{version}')
async def api_versions_clear(tool: str, version: str, request: Request, auth: AuthContext = Depends(require_admin)):
    return await _api_action('clear', tool, request, auth, version)
