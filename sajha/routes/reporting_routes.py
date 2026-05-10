"""
SAJHA MCP Server v3 — Reporting Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

All reporting queries go through ToolUsageDAO. No raw SQL.
Both API (JSON) and web UI (template) endpoints.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sajha.db.engine import get_db
from sajha.db.dao import ToolUsageDAO, AuditDAO
from sajha.auth import require_auth, require_admin, AuthContext
from sajha.app import render

router = APIRouter(tags=['reporting'])


def _parse_period(period: str) -> tuple[datetime, datetime]:
    """Convert period string like '24h', '7d', '30d' to (since, until) datetimes."""
    now = datetime.now(timezone.utc)
    if period.endswith('h'):
        hours = int(period[:-1])
        return now - timedelta(hours=hours), now
    elif period.endswith('d'):
        days = int(period[:-1])
        return now - timedelta(days=days), now
    # Default 24h
    return now - timedelta(hours=24), now


# ── API Endpoints ────────────────────────────────────────────────

@router.get('/api/reports/overview')
async def api_report_overview(
    period: str = Query('24h'),
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    since, until = _parse_period(period)
    hours = int((until - since).total_seconds() / 3600)
    dao = ToolUsageDAO(db)
    overview = dao.get_overview(period_hours=hours)
    return JSONResponse(overview)


@router.get('/api/reports/tools/usage')
async def api_report_tools_usage(
    period: str = Query('7d'),
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    since, until = _parse_period(period)
    dao = ToolUsageDAO(db)
    data = dao.get_usage_by_tool(since, until)
    return JSONResponse({'period': period, 'tools': data})


@router.get('/api/reports/tools/{tool_name}/detail')
async def api_report_tool_detail(
    tool_name: str,
    period: str = Query('30d'),
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    _, _ = _parse_period(period)
    days = int(period.rstrip('dh'))
    dao = ToolUsageDAO(db)
    detail = dao.get_tool_detail(tool_name, days=days)
    return JSONResponse(detail)


@router.get('/api/reports/users/activity')
async def api_report_users_activity(
    period: str = Query('30d'),
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    since, until = _parse_period(period)
    dao = ToolUsageDAO(db)
    data = dao.get_usage_by_user(since, until)
    return JSONResponse({'period': period, 'users': data})


@router.get('/api/reports/heatmap')
async def api_report_heatmap(
    days: int = Query(30),
    tool: str = Query(None),
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    dao = ToolUsageDAO(db)
    data = dao.get_hourly_heatmap(days=days, tool_name=tool)
    return JSONResponse({'days': days, 'tool': tool, 'heatmap': data})


@router.get('/api/reports/audit')
async def api_report_audit(
    limit: int = Query(100),
    action: str = Query(None),
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    dao = AuditDAO(db)
    entries = dao.get_recent(limit=limit, action=action)
    return JSONResponse({'audit': [
        {
            'timestamp': e.timestamp.isoformat(),
            'actor': e.actor_id,
            'action': e.action,
            'resource_type': e.resource_type,
            'resource_id': e.resource_id,
            'details': e.details,
        }
        for e in entries
    ]})


# ── Web UI Endpoints ─────────────────────────────────────────────

@router.get('/reports')
async def reports_dashboard(
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    dao = ToolUsageDAO(db)
    overview_24h = dao.get_overview(24)
    overview_7d = dao.get_overview(24 * 7)
    overview_30d = dao.get_overview(24 * 30)

    since_7d = datetime.now(timezone.utc) - timedelta(days=7)
    until = datetime.now(timezone.utc)
    top_tools = dao.get_usage_by_tool(since_7d, until)[:10]
    top_users = dao.get_usage_by_user(since_7d, until)[:10]

    return render(request, 'reporting/reports_dashboard.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'overview_24h': overview_24h,
        'overview_7d': overview_7d,
        'overview_30d': overview_30d,
        'top_tools': top_tools,
        'top_users': top_users,
    })
