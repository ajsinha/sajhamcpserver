"""
SAJHA MCP Server — Monitoring routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Help, About, the guides and the glossary are in help_routes.py.
"""

from fastapi import APIRouter, Request, Depends
from sajha.auth import require_admin, AuthContext
from sajha.app import render

router = APIRouter(tags=['misc'])


# ── Monitoring ───────────────────────────────────────────────────

@router.get('/monitoring/tools')
async def monitoring_tools(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.app import tools_registry
    metrics = tools_registry.get_tool_metrics() if tools_registry else []
    return render(request, 'monitoring/monitoring_tools.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'metrics': metrics,
        'is_admin': True,
    })


@router.get('/monitoring/users')
async def monitoring_users(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.db.engine import get_db_session
    from sajha.db.dao import UserDAO
    db = get_db_session()
    try:
        dao = UserDAO(db)
        users = dao.get_all_users()
        admin_count = sum(1 for u in users if u.is_admin)
        users_data = [
            {
                'user_id': u.user_id,
                'user_name': u.user_name,
                'roles': u.role_names,
                'enabled': u.enabled,
                'last_login': u.last_login.isoformat() if u.last_login else None,
            }
            for u in users
        ]
    finally:
        db.close()

    return render(request, 'monitoring/monitoring_users.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'users': users_data,
        'admin_count': admin_count,
        'is_admin': True,
    })
