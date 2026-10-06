"""
SAJHA MCP Server — observability routes: /metrics, the Usage & cost dashboard and its API.

  GET /metrics                          Prometheus text format (observability.metrics.auth)
  GET /monitoring/usage                 the dashboard (admin: everyone; others: their own calls)
  GET /api/observability/usage          every figure the dashboard shows (JSON)
  GET /api/observability/usage.csv      one table as CSV (?dimension=user|api_key|role|model|tool|day)
  GET /api/observability/alerts         alert rules and their state (admin)
  GET /api/observability/status         effective settings and the OpenTelemetry state (admin)

Design: docs/architecture/Observability.md.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

from __future__ import annotations

import csv
import io
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.concurrency import run_in_threadpool

from sajha.app import render
from sajha.auth import AuthContext, require_admin, require_auth

router = APIRouter(tags=['observability'])


@router.get('/metrics', include_in_schema=False)
async def prometheus_metrics(request: Request):
    from sajha.observability import settings as S
    from sajha.observability.metrics import CONTENT_TYPE, exposition
    from sajha.observability.server import authorize
    if not S.metrics_enabled():
        return PlainTextResponse('metrics are disabled (observability.metrics.enabled)', status_code=404)
    ok, status, why = await run_in_threadpool(authorize, request.headers, request.cookies)
    if not ok:
        headers = {'WWW-Authenticate': 'Bearer realm="sajha-metrics"'} if status == 401 else None
        return PlainTextResponse(why, status_code=status, headers=headers)
    body = await run_in_threadpool(exposition)
    return Response(body, media_type=CONTENT_TYPE)


def _filters(auth: AuthContext, user: str, api_key: str, role: str, provider: str, model: str,
             tool: str) -> Dict[str, str]:
    f = {'user': user, 'api_key': api_key, 'role': role, 'provider': provider, 'model': model, 'tool': tool}
    if not auth.is_admin:                       # everyone else sees only their own calls
        f['user'] = auth.user_id or 'anonymous'
        f['api_key'] = ''
    return {k: (v or '').strip() for k, v in f.items() if v and v.strip()}


def _report(since: Optional[str], until: Optional[str], filters: Dict[str, str], is_admin: bool) -> Dict:
    from sajha.observability import usage
    usage.flush()
    rep = usage.report(since, until, filters)
    users = [r['key'] for r in rep['by_user']]
    roles = [r['key'] for r in rep['by_role']]
    rep['budgets'] = usage.budgets(users, roles if is_admin else roles)
    if not is_admin:
        rep['budgets']['roles'] = [r for r in rep['budgets']['roles'] if r['key'] in roles]
    rep['scope'] = 'all' if is_admin else 'self'
    return rep


@router.get('/api/observability/usage')
async def api_usage(since: Optional[str] = None, until: Optional[str] = None, user: str = '', api_key: str = '',
                    role: str = '', provider: str = '', model: str = '', tool: str = '',
                    auth: AuthContext = Depends(require_auth)):
    f = _filters(auth, user, api_key, role, provider, model, tool)
    return JSONResponse(await run_in_threadpool(_report, since, until, f, auth.is_admin))


@router.get('/api/observability/usage.csv')
async def api_usage_csv(dimension: str = Query('user'), since: Optional[str] = None, until: Optional[str] = None,
                        user: str = '', api_key: str = '', role: str = '', provider: str = '', model: str = '',
                        tool: str = '', auth: AuthContext = Depends(require_auth)):
    from sajha.observability import usage
    if dimension not in usage.DIMENSIONS:
        return JSONResponse({'error': f'dimension must be one of {", ".join(usage.DIMENSIONS)}'}, status_code=400)
    f = _filters(auth, user, api_key, role, provider, model, tool)
    rep = await run_in_threadpool(_report, since, until, f, auth.is_admin)
    buf = io.StringIO()
    w = csv.writer(buf)
    for row in usage.csv_rows(rep, dimension):
        w.writerow(row)
    name = f'sajha-usage-{dimension}-{rep["since"]}-{rep["until"]}.csv'
    return Response(buf.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{name}"'})


@router.get('/api/observability/alerts')
async def api_alerts(auth: AuthContext = Depends(require_admin)):
    from sajha.observability.alerts import get_alert_manager
    m = get_alert_manager()
    return JSONResponse({'rules': [r.to_dict() for r in (m.rules if m else [])],
                         'recent': list(m.sent) if m else []})


@router.get('/api/observability/status')
async def api_status(auth: AuthContext = Depends(require_admin)):
    from sajha.observability import settings as S, tracing
    return JSONResponse({**S.describe(), 'otel': {**S.describe()['otel'], **tracing.status()}})


@router.get('/monitoring/usage')
async def monitoring_usage(request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.observability import settings as S
    return render(request, 'monitoring/usage.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'me': auth.user_id,
        'usage_enabled': S.get_bool('observability.usage.enabled', True),
    })
