# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""
SAJHA MCP Server v3 — Tools Routes (Web UI)
"""

import json
import logging
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sajha.db.engine import get_db
from sajha.auth import require_auth, require_admin, AuthContext
from sajha.app import render

logger = logging.getLogger(__name__)
router = APIRouter(tags=['tools'])


def _visible(auth: AuthContext, tool_name: str) -> bool:
    from sajha.auth.access import policy_for
    return policy_for(auth).can_see(tool_name)


def tool_domain(registry, tool: dict) -> dict:
    """The Tools page's grouping of one tool: ``folder`` (its tool folder; '' at the root; None without a
    config file), ``domain`` (the folder; a proxied MCP server tool's prefix; a remote SAJHA Net tool's
    published folder, when its host sends one) and ``unfiled`` (a local tool with no domain: the root)."""
    name = str(tool.get('name') or '')
    net = ((tool.get('_meta') or {}).get('io.sajha/net') or {})
    if net.get('locality') == 'remote':
        folder = net.get('folder') if isinstance(net.get('folder'), str) else ''
        return {'folder': folder or None, 'domain': folder, 'unfiled': False}
    tool_folder = getattr(registry, 'tool_folder', None)
    folder = tool_folder(name) if callable(tool_folder) else None
    if folder:
        return {'folder': folder, 'domain': folder, 'unfiled': False}
    if folder is None and '__' in name:            # a proxied (federated or external) MCP server's tool
        return {'folder': None, 'domain': name.split('__', 1)[0], 'unfiled': False}
    return {'folder': folder, 'domain': '', 'unfiled': True}


@router.get('/tools')
async def tools_list(request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import tools_registry
    from sajha.auth.access import policy_for
    tools = tools_registry.get_all_tools() if tools_registry else []
    policy = policy_for(auth)       # the MCP tools/list visibility (sajha/auth/access.py)
    if not policy.unrestricted():
        tools = [t for t in tools if policy.can_see(t.get('name'))]
    tools = [dict(t, **tool_domain(tools_registry, t)) for t in tools]
    tool_errors = tools_registry.get_tool_errors() if tools_registry else {}
    return render(request, 'tools/tools_list.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'tools': tools,
        'tool_errors': tool_errors,
        'is_admin': auth.is_admin,
    })


@router.get('/tools/{tool_name}/execute')
async def tool_execute_page(tool_name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import tools_registry
    tool = tools_registry.get_tool(tool_name) if tools_registry else None
    if tool and not _visible(auth, tool_name):
        tool = None                 # hidden from this caller: the same answer as no such tool
    if not tool:
        return render(request, 'common/error.html', {
            'error': 'Tool Not Found',
            'message': f'Tool "{tool_name}" does not exist',
        }, status_code=404)

    return render(request, 'tools/tool_execute.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'tool': tool.to_mcp_format(),
        'tool_name': tool_name,
        'tool_enabled': tool.enabled,
        'tool_version': getattr(tool, 'version', settings.app_version if 'settings' in dir() else '4.5.0'),
        'is_admin': auth.is_admin,
    })


@router.get('/tools/{tool_name}/schema')
async def tool_schema_page(tool_name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import tools_registry
    tool = tools_registry.get_tool(tool_name) if tools_registry else None
    if tool and not _visible(auth, tool_name):
        tool = None                 # hidden from this caller: the same answer as no such tool
    if not tool:
        return render(request, 'common/error.html', {
            'error': 'Tool Not Found',
            'message': f'Tool "{tool_name}" does not exist',
        }, status_code=404)

    import json
    tool_data = tool.to_mcp_format()
    tool_cfg = tools_registry.tool_configs.get(tool_name, {})
    
    return render(request, 'tools/tool_schema.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'tool': tool_data,
        'tool_name': tool_name,
        'tool_config': tool_cfg,
        'tool_enabled': tool.enabled,
        'tool_version': getattr(tool, 'version', settings.app_version if 'settings' in dir() else '4.5.0'),
        'schema_json': json.dumps(tool_data.get('inputSchema', {}), indent=2, default=str),
        # admin only, as on /tools/{name}/config: the config holds resolved ${...} values
        'config_json': json.dumps(tool_cfg, indent=2, default=str) if auth.is_admin else '',
        'is_admin': auth.is_admin,
    })


@router.get('/tools/{tool_name}/config')
async def tool_config_page(tool_name: str, request: Request, auth: AuthContext = Depends(require_admin)):
    # admin only: tool configs hold resolved ${...} values, API keys included
    from sajha.app import tools_registry
    tool = tools_registry.get_tool(tool_name) if tools_registry else None
    config = tools_registry.tool_configs.get(tool_name, {}) if tools_registry else {}
    return render(request, 'tools/tool_config.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'tool_name': tool_name,
        'tool_config': config,
        'tool_config_json': json.dumps(config, indent=2),
        'tool_file': tools_registry.tool_path(tool_name) if hasattr(tools_registry, 'tool_path') else None,
        'is_admin': auth.is_admin,
    })
