"""
SAJHA MCP Server v3 — API Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

All JSON API endpoints for programmatic access.
Same URLs as v2 for backward compatibility.
"""

import io
import csv
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from sajha.db.engine import get_db
from sajha.db.dao import ToolUsageDAO, AuditDAO, UserDAO, ApiKeyDAO
from sajha.auth import (
    AuthManager, AuthContext,
    get_current_user, require_auth, require_admin,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=['api'])


# ── MCP Protocol Endpoint ────────────────────────────────────────

@router.post('/mcp')
@router.post('/api/mcp')
async def mcp_endpoint(request: Request, db: Session = Depends(get_db)):
    """MCP JSON-RPC 2.0 endpoint (same as v2)."""
    from sajha.app import mcp_handler

    auth = AuthManager.authenticate_request(request, db)
    session_data = auth.to_legacy_session() if auth.authenticated else None

    try:
        request_data = await request.json()
    except Exception:
        return JSONResponse({
            'jsonrpc': '2.0',
            'error': {'code': -32700, 'message': 'Parse error'},
        }, status_code=400)

    response = mcp_handler.handle_request(request_data, session_data)
    return JSONResponse(response)


# ── Tool Execution API ───────────────────────────────────────────

@router.post('/api/tools/execute')
async def api_tool_execute(
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
):
    """Execute a tool via API. Logs usage to database."""
    from sajha.app import tools_registry

    data = await request.json()
    tool_name = data.get('tool')
    arguments = data.get('arguments', {})

    if not tool_name:
        return JSONResponse({'error': 'Tool name required'}, status_code=400)

    if not auth.has_tool_access(tool_name):
        return JSONResponse({'error': f'Access denied to tool: {tool_name}'}, status_code=403)

    tool = tools_registry.get_tool(tool_name) if tools_registry else None
    if not tool:
        return JSONResponse({'error': 'Tool not found'}, status_code=404)

    # Execute with timing
    usage_dao = ToolUsageDAO(db)
    start = time.time()
    try:
        result = tool.execute_with_tracking(arguments)
        duration_ms = int((time.time() - start) * 1000)

        # Log to DB
        usage_dao.log_execution(
            tool_name=tool_name,
            user_id=auth.user_id,
            auth_type=auth.auth_type,
            duration_ms=duration_ms,
            success=True,
            arguments=arguments,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get('User-Agent'),
        )

        return JSONResponse({'success': True, 'result': result})
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        usage_dao.log_execution(
            tool_name=tool_name,
            user_id=auth.user_id,
            auth_type=auth.auth_type,
            duration_ms=duration_ms,
            success=False,
            error_message=str(e),
            arguments=arguments,
            client_ip=request.client.host if request.client else None,
        )
        return JSONResponse({'success': False, 'error': str(e)}, status_code=500)


# ── Tool Listing API ─────────────────────────────────────────────

@router.get('/api/tools/list')
async def api_tools_list():
    """Get list of all tools (public)."""
    from sajha.app import tools_registry
    tools = tools_registry.get_all_tools() if tools_registry else []
    return JSONResponse({'tools': tools})


@router.get('/api/tools/{tool_name}/schema')
async def api_tool_schema(tool_name: str):
    from sajha.app import tools_registry
    tool = tools_registry.get_tool(tool_name) if tools_registry else None
    if not tool:
        return JSONResponse({'error': 'Tool not found'}, status_code=404)
    return JSONResponse(tool.to_mcp_format())


# ── Admin: Tool Management ───────────────────────────────────────

@router.post('/api/admin/tools/{tool_name}/enable')
async def api_enable_tool(tool_name: str, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    from sajha.app import tools_registry
    if tools_registry.enable_tool(tool_name):
        AuditDAO(db).log('tool.enable', auth.user_id, 'tool', tool_name)
        return JSONResponse({'success': True})
    return JSONResponse({'error': 'Tool not found'}, status_code=404)


@router.post('/api/admin/tools/{tool_name}/disable')
async def api_disable_tool(tool_name: str, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    from sajha.app import tools_registry
    if tools_registry.disable_tool(tool_name):
        AuditDAO(db).log('tool.disable', auth.user_id, 'tool', tool_name)
        return JSONResponse({'success': True})
    return JSONResponse({'error': 'Tool not found'}, status_code=404)


@router.get('/api/admin/tools/{tool_name}/config')
async def api_get_tool_config(tool_name: str, auth: AuthContext = Depends(require_admin)):
    from sajha.app import tools_registry
    if tool_name in tools_registry.tool_configs:
        return JSONResponse(tools_registry.tool_configs[tool_name])
    tool = tools_registry.get_tool(tool_name)
    if tool:
        return JSONResponse(tool.config)
    return JSONResponse({'error': 'Tool not found'}, status_code=404)


@router.post('/api/admin/tools/{tool_name}/config')
async def api_save_tool_config(tool_name: str, request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    from sajha.app import tools_registry
    config = await request.json()
    if not config:
        return JSONResponse({'error': 'No configuration provided'}, status_code=400)

    tools_registry.tool_configs[tool_name] = config
    tools_registry._save_tool_config(tool_name)

    if tool_name in tools_registry.tools:
        tools_registry.unregister_tool(tool_name)
    config_file = Path(tools_registry.tools_config_dir) / f'{tool_name}.json'
    if config_file.exists():
        tools_registry.load_tool_from_config(config_file)

    AuditDAO(db).log('tool.config_update', auth.user_id, 'tool', tool_name)
    return JSONResponse({'success': True, 'message': 'Configuration saved'})


@router.post('/api/admin/tools/reload')
async def api_reload_tools(auth: AuthContext = Depends(require_admin)):
    from sajha.app import tools_registry
    tools_registry.reload_all_tools()
    return JSONResponse({'success': True, 'message': 'Tools reloaded'})


# ── Admin: User Management ───────────────────────────────────────

@router.get('/api/admin/users')
async def api_list_users(auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    user_dao = UserDAO(db)
    users = user_dao.get_all_users()
    return JSONResponse({'users': [
        {
            'user_id': u.user_id,
            'user_name': u.user_name,
            'email': u.email,
            'roles': u.role_names,
            'enabled': u.enabled,
            'created_at': u.created_at.isoformat() if u.created_at else None,
            'last_login': u.last_login.isoformat() if u.last_login else None,
        }
        for u in users
    ]})


@router.post('/api/admin/users/create')
async def api_create_user(
    request: Request,
    auth: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from sajha.db.models import User, Role
    from sajha.db.dao import RoleDAO
    from sajha.auth.password import hash_password

    data = await request.json()
    user_id = data.get('user_id')
    if not user_id:
        return JSONResponse({'error': 'user_id required'}, status_code=400)

    user_dao = UserDAO(db)
    if user_dao.user_exists(user_id):
        return JSONResponse({'error': 'User already exists'}, status_code=409)

    role_dao = RoleDAO(db)
    user = User(
        user_id=user_id,
        user_name=data.get('user_name', user_id),
        email=data.get('email', ''),
        password_hash=hash_password(data.get('password', 'changeme')),
        enabled=data.get('enabled', True),
    )
    for rname in data.get('roles', ['user']):
        role = role_dao.get_or_create(rname)
        user.roles.append(role)
    user_dao.create(user)

    AuditDAO(db).log('user.create', auth.user_id, 'user', user_id)
    return JSONResponse({'success': True, 'user_id': user_id})


@router.post('/api/admin/users/{uid}/enable')
async def api_enable_user(uid: str, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    user_dao = UserDAO(db)
    user = user_dao.get_by_user_id(uid)
    if not user:
        return JSONResponse({'error': 'User not found'}, status_code=404)
    user.enabled = True
    user_dao.update(user)
    AuditDAO(db).log('user.enable', auth.user_id, 'user', uid)
    return JSONResponse({'success': True})


@router.post('/api/admin/users/{uid}/disable')
async def api_disable_user(uid: str, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    if uid == 'admin':
        return JSONResponse({'error': 'Cannot disable admin'}, status_code=400)
    user_dao = UserDAO(db)
    user = user_dao.get_by_user_id(uid)
    if not user:
        return JSONResponse({'error': 'User not found'}, status_code=404)
    user.enabled = False
    user_dao.update(user)
    AuditDAO(db).log('user.disable', auth.user_id, 'user', uid)
    return JSONResponse({'success': True})


@router.delete('/api/admin/users/{uid}/delete')
async def api_delete_user(uid: str, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    if uid == 'admin':
        return JSONResponse({'error': 'Cannot delete admin'}, status_code=400)
    user_dao = UserDAO(db)
    user = user_dao.get_by_user_id(uid)
    if not user:
        return JSONResponse({'error': 'User not found'}, status_code=404)
    user_dao.delete(user)
    AuditDAO(db).log('user.delete', auth.user_id, 'user', uid)
    return JSONResponse({'success': True})


# ── Metrics Export ───────────────────────────────────────────────

# ── Tool Groups API (used by Help page) ─────────────────────────

@router.get('/api/tool-groups/search')
async def api_tool_group_search(q: str = ''):
    """Search tools by name or description across all groups."""
    from sajha.app import tools_registry
    if not tools_registry or not q or len(q) < 2:
        return JSONResponse({'results': [], 'count': 0, 'query': q})

    query_lower = q.lower()
    colors = ['primary', 'success', 'info', 'warning', 'danger', 'secondary']
    icons = ['bi-tools', 'bi-graph-up', 'bi-database', 'bi-globe', 'bi-bank', 'bi-search']
    results = []

    for name, tool in tools_registry.tools.items():
        cfg = getattr(tool, 'config', {}) or {}
        desc = cfg.get('description', '')
        if query_lower in name.lower() or query_lower in desc.lower():
            prefix = name.split('_')[0] if '_' in name else name
            idx = hash(prefix) % len(colors)
            results.append({
                'name': name,
                'description': desc,
                'enabled': cfg.get('enabled', True),
                'group': prefix,
                'group_color': colors[idx],
                'group_icon': icons[idx],
            })

    results.sort(key=lambda t: t['name'])
    return JSONResponse({'results': results[:50], 'count': len(results), 'query': q})


@router.get('/api/tool-groups/{group_name}')
async def api_tool_group_detail(group_name: str):
    """Get all tools belonging to a specific tool group."""
    from sajha.app import tools_registry
    if not tools_registry:
        return JSONResponse({'error': 'Tools not loaded'}, status_code=503)

    tools_in_group = []
    for name, tool in tools_registry.tools.items():
        prefix = name.split('_')[0] if '_' in name else name
        if prefix == group_name:
            cfg = getattr(tool, 'config', {}) or {}
            tools_in_group.append({
                'name': name,
                'description': cfg.get('description', ''),
                'enabled': cfg.get('enabled', True),
                'category': (cfg.get('metadata') or {}).get('category', ''),
            })

    tools_in_group.sort(key=lambda t: t['name'])

    colors = ['primary', 'success', 'info', 'warning', 'danger', 'secondary']
    icons = ['bi-tools', 'bi-graph-up', 'bi-database', 'bi-globe', 'bi-bank', 'bi-search']
    group_idx = hash(group_name) % len(colors)

    return JSONResponse({
        'group': {
            'name': group_name,
            'description': f'{len(tools_in_group)} tools in the {group_name} provider group',
            'color': colors[group_idx],
            'icon': icons[group_idx],
            'categories': list({t['category'] for t in tools_in_group if t['category']}),
        },
        'tools': tools_in_group,
    })


@router.get('/api/admin/tools/metrics/export')
async def api_export_metrics(auth: AuthContext = Depends(require_admin)):
    from sajha.app import tools_registry
    metrics = tools_registry.get_tool_metrics() if tools_registry else []

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Tool Name', 'Version', 'Status', 'Execution Count', 'Avg Time (s)', 'Last Execution'])
    for m in metrics:
        writer.writerow([
            m.get('name', ''),
            m.get('version', ''),
            'Enabled' if m.get('enabled') else 'Disabled',
            m.get('execution_count', 0),
            f"{m.get('average_execution_time', 0):.3f}",
            m.get('last_execution', 'Never'),
        ])

    output.seek(0)
    filename = f'tool_metrics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'},
    )
