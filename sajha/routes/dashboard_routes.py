"""
SAJHA MCP Server v3 — Dashboard Routes
"""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from sajha.db.engine import get_db
from sajha.db.dao import UserDAO
from sajha.auth import require_auth, AuthContext
from sajha.app import render

router = APIRouter(tags=['dashboard'])


@router.get('/dashboard')
async def dashboard(
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    from sajha.app import tools_registry, prompts_registry

    user_dao = UserDAO(db)
    users_count = user_dao.count()
    tools = tools_registry.get_all_tools() if tools_registry else []
    tool_errors = tools_registry.get_tool_errors() if tools_registry else {}

    return render(request, 'dashboard/dashboard.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'tools': tools,
        'tool_errors': tool_errors,
        'tools_count': len(tools),
        'prompts_count': len(prompts_registry.prompts) if prompts_registry else 0,
        'users_count': users_count,
        'is_admin': auth.is_admin,
    })
