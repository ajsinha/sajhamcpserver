"""
SAJHA MCP Server v3 — Admin Web UI Routes
"""

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from sajha.db.engine import get_db
from sajha.db.dao import UserDAO
from sajha.auth import require_admin, AuthContext
from sajha.app import render

router = APIRouter(prefix='/admin', tags=['admin'])


@router.get('/users')
async def admin_users_page(
    request: Request,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user_dao = UserDAO(db)
    users = user_dao.get_all_users()
    # Convert to dicts for template compatibility
    users_list = [
        {
            'user_id': u.user_id,
            'user_name': u.user_name,
            'email': u.email or '',
            'roles': u.role_names,
            'enabled': u.enabled,
            'created_at': u.created_at.isoformat() + 'Z' if u.created_at else '',
            'last_login': u.last_login.isoformat() + 'Z' if u.last_login else None,
        }
        for u in users
    ]
    return render(request, 'admin/admin_users.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'users': users_list,
        'is_admin': True,
    })


@router.get('/users/create')
async def admin_user_create_page(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.app import tools_registry
    tools = list(tools_registry.tools.keys()) if tools_registry else []
    return render(request, 'admin/admin_user_create.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'available_tools': tools,
        'is_admin': True,
    })


@router.get('/tools')
async def admin_tools_page(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.app import tools_registry
    tools = tools_registry.get_all_tools() if tools_registry else []
    tool_errors = tools_registry.get_tool_errors() if tools_registry else {}
    metrics = tools_registry.get_tool_metrics() if tools_registry else []
    return render(request, 'admin/admin_tools.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'tools': tools,
        'tool_errors': tool_errors,
        'metrics': metrics,
        'is_admin': True,
    })
