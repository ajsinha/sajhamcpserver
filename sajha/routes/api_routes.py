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
# POST/GET/DELETE /mcp (Streamable HTTP transport) live in mcp_routes.py.


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
    from sajha.observability.caller import from_auth, set_caller
    set_caller(from_auth(auth))      # the usage ledger's caller (this request's context only)
    from sajha.policy.context import set_source      # policy rules can match the source
    set_source('playground' if request.headers.get('X-SAJHA-Client') == 'playground' else 'rest')
    from sajha.quality import versions as _versions    # a versioned tool says which version ran
    try:
        with _versions.collect_meta() as version_meta:
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

        body = {'success': not getattr(result, 'is_error', False), 'result': result}
        if version_meta:
            body['_meta'] = version_meta
        status = getattr(result, 'http_status', None)
        if status:       # an LLM tool that refused the run to protect the process (busy): 503 + Retry-After
            retry = getattr(result, 'retry_after', None)
            return JSONResponse(body, status_code=int(status),
                                headers={'Retry-After': str(int(retry))} if retry else None)
        return JSONResponse(body)
    except Exception as e:
        from sajha.accounts.errors import ConnectedAccountRequired
        if isinstance(e, ConnectedAccountRequired):     # 428 + connect_url (sajha/accounts/respond.py)
            from sajha.accounts.respond import rest_response
            return rest_response(e)
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
        from sajha.tools.base_mcp_tool import ToolArgumentError
        from sajha.policy.errors import ApprovalRequired, PolicyError, RateLimited
        if isinstance(e, PolicyError):
            # 403 denied, 202 approval pending, 429 rate limited (docs/architecture/Policy and Audit.md)
            body = {'success': False, 'error': str(e), 'policy': e.to_dict()}
            if isinstance(e, ApprovalRequired):
                body['approval_id'] = e.approval_id
            headers = {'Retry-After': str(int(e.retry_after or 1))} if isinstance(e, RateLimited) else None
            return JSONResponse(body, status_code=e.http_status, headers=headers)
        status = 400 if isinstance(e, ToolArgumentError) else 500   # 400: arguments fail the inputSchema
        return JSONResponse({'success': False, 'error': str(e)}, status_code=status)


# ── Tool Listing API ─────────────────────────────────────────────

async def _catalog_policy(request: Request, db: Session):
    """(ToolPolicy, error response) for the REST catalog: the same gate and visibility as
    MCP ``tools/list`` (sajha/auth/access.py). Signed-in users see their roles' tools, API
    keys their allowlist, credential-less callers the ``mcp.anonymous`` policy; a 401 where
    ``/mcp`` would answer one (``mcp.auth.mode: required``, anonymous access disabled, or
    credentials that do not authenticate)."""
    from sajha.auth.access import policy_for
    from sajha.auth.oauth.resource_server import authorize_mcp
    auth, err = await authorize_mcp(request, db, 'tools/list')
    if err is not None:
        return None, err
    return policy_for(auth), None


@router.get('/api/tools/list')
async def api_tools_list(request: Request, db: Session = Depends(get_db)):
    """The tools this caller may see (the MCP tools/list policy)."""
    from sajha.app import tools_registry
    policy, err = await _catalog_policy(request, db)
    if err is not None:
        return err
    tools = tools_registry.get_all_tools() if tools_registry else []
    if not policy.unrestricted():
        tools = [t for t in tools if policy.can_see(t.get('name'))]
    return JSONResponse({'tools': tools})


@router.get('/api/tools/{tool_name}/schema')
async def api_tool_schema(tool_name: str, request: Request, db: Session = Depends(get_db)):
    from sajha.app import tools_registry
    policy, err = await _catalog_policy(request, db)
    if err is not None:
        return err
    tool = tools_registry.get_tool(tool_name) if tools_registry else None
    if not tool or not policy.can_see(tool_name):     # a hidden tool is indistinguishable from none
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
    tools_registry.load_tool_from_config(f'{tool_name}.json')

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

    from sajha.auth.password import password_problem
    password = data.get('password')
    problem = password_problem(password if isinstance(password, str) else '', user_id)
    if problem:
        return JSONResponse({'error': f'password: {problem}'}, status_code=400)

    role_dao = RoleDAO(db)
    user = User(
        user_id=user_id,
        user_name=data.get('user_name', user_id),
        email=data.get('email', ''),
        password_hash=hash_password(password),
        enabled=data.get('enabled', True),
    )
    # an admin chose this password: the user replaces it at first sign-in
    user.must_change_password = bool(data.get('must_change_password', True))
    for rname in data.get('roles', ['user']):
        role = role_dao.get_or_create(rname)
        user.roles.append(role)
    user_dao.create(user)

    AuditDAO(db).log('user.create', auth.user_id, 'user', user_id)
    # every account has a default API key (sajha/auth/apikeys.py); the user rotates it to see it
    try:
        from sajha.auth.apikeys import ensure_default_key
        ensure_default_key(db, user, by=auth.user_id)
    except Exception as e:
        logger.warning(f'default API key for {user_id} not created: {e}')
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
    from sajha.auth.apikeys import forget_user
    forget_user(db, user)      # persistent key records of this user's keys (the rows go with the user)
    user_dao.delete(user)
    AuditDAO(db).log('user.delete', auth.user_id, 'user', uid)
    return JSONResponse({'success': True})


# ── Metrics Export ───────────────────────────────────────────────

# ── Tool Groups API (used by Help page) ─────────────────────────

@router.get('/api/tool-groups/search')
async def api_tool_group_search(request: Request, q: str = '', db: Session = Depends(get_db)):
    """Search the tools this caller may see by name or description."""
    from sajha.app import tools_registry
    policy, err = await _catalog_policy(request, db)
    if err is not None:
        return err
    if not tools_registry or not q or len(q) < 2:
        return JSONResponse({'results': [], 'count': 0, 'query': q})

    query_lower = q.lower()
    colors = ['primary', 'success', 'info', 'warning', 'danger', 'secondary']
    icons = ['bi-tools', 'bi-graph-up', 'bi-database', 'bi-globe', 'bi-bank', 'bi-search']
    results = []

    for name, tool in tools_registry.tools.items():
        if not policy.can_see(name):
            continue
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
async def api_tool_group_detail(group_name: str, request: Request, db: Session = Depends(get_db)):
    """The tools of one tool group that this caller may see."""
    from sajha.app import tools_registry
    policy, err = await _catalog_policy(request, db)
    if err is not None:
        return err
    if not tools_registry:
        return JSONResponse({'error': 'Tools not loaded'}, status_code=503)

    tools_in_group = []
    for name, tool in tools_registry.tools.items():
        prefix = name.split('_')[0] if '_' in name else name
        if prefix == group_name and policy.can_see(name):
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
