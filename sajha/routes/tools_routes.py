"""
SAJHA MCP Server v3 — Tools Routes (Web UI)
"""

import json
import logging
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sajha.db.engine import get_db
from sajha.auth import require_auth, AuthContext
from sajha.app import render

logger = logging.getLogger(__name__)
router = APIRouter(tags=['tools'])


@router.get('/tools')
async def tools_list(request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import tools_registry
    tools = tools_registry.get_all_tools() if tools_registry else []
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
    if not tool:
        return render(request, 'common/error.html', {
            'error': 'Tool Not Found',
            'message': f'Tool "{tool_name}" does not exist',
        }, status_code=404)

    return render(request, 'tools/tool_execute.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'tool': tool.to_mcp_format(),
        'tool_name': tool_name,
        'is_admin': auth.is_admin,
    })


@router.get('/tools/{tool_name}/schema')
async def tool_schema_page(tool_name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import tools_registry
    tool = tools_registry.get_tool(tool_name) if tools_registry else None
    if not tool:
        return render(request, 'common/error.html', {
            'error': 'Tool Not Found',
            'message': f'Tool "{tool_name}" does not exist',
        }, status_code=404)

    return render(request, 'tools/tool_schema.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'tool': tool.to_mcp_format(),
        'tool_name': tool_name,
        'tool_config': tools_registry.tool_configs.get(tool_name, {}),
        'is_admin': auth.is_admin,
    })


@router.get('/tools/{tool_name}/config')
async def tool_config_page(tool_name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import tools_registry
    tool = tools_registry.get_tool(tool_name) if tools_registry else None
    config = tools_registry.tool_configs.get(tool_name, {}) if tools_registry else {}
    return render(request, 'tools/tool_config.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'tool_name': tool_name,
        'tool_config': config,
        'tool_config_json': json.dumps(config, indent=2),
        'is_admin': auth.is_admin,
    })
