"""
SAJHA MCP Server v3 — A2A (Agent-to-Agent) Protocol Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Implements Google's A2A protocol for inter-agent communication.
See: https://google.github.io/A2A/

Endpoints:
    GET  /.well-known/agent.json  — Agent Card (discovery)
    POST /a2a                     — Task lifecycle (JSON-RPC 2.0)
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sajha.db.engine import get_db
from sajha.db.models import A2ATask
from sajha.db.dao import A2ATaskDAO
from sajha.auth import get_current_user, AuthContext
from sajha.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=['a2a'])


# ── Agent Card ───────────────────────────────────────────────────

@router.get('/.well-known/agent.json')
async def agent_card():
    """
    A2A Agent Card — tells other agents what this server can do.
    """
    settings = get_settings()
    from sajha.app import tools_registry

    # Build skills from tool registry
    skills = []
    if tools_registry:
        for tool_name, tool in list(tools_registry.tools.items())[:50]:
            tool_data = tool.to_mcp_format()
            skills.append({
                'id': tool_name,
                'name': tool_data.get('name', tool_name),
                'description': tool_data.get('description', ''),
                'tags': tool_data.get('tags', []),
                'examples': [],
            })

    return JSONResponse({
        'name': settings.app_name,
        'description': settings.app_description,
        'url': f'http://{settings.server_host}:{settings.server_port}/a2a',
        'version': settings.app_version,
        'capabilities': {
            'streaming': False,
            'pushNotifications': False,
            'stateTransitionHistory': True,
        },
        'authentication': {
            'schemes': ['bearer', 'apikey'],
        },
        'skills': skills,
        'defaultInputModes': ['text'],
        'defaultOutputModes': ['text'],
    })


# ── A2A Task Endpoint ────────────────────────────────────────────

@router.post('/a2a')
async def a2a_endpoint(
    request: Request,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    A2A JSON-RPC 2.0 endpoint — handles task lifecycle methods:
        tasks/send      — Submit a new task
        tasks/get       — Get task status
        tasks/cancel    — Cancel a task
    """
    try:
        body = await request.json()
    except Exception as e:
        return JSONResponse({
            'jsonrpc': '2.0',
            'error': {'code': -32700, 'message': 'Parse error'},
        }, status_code=400)

    method = body.get('method', '')
    params = body.get('params', {})
    req_id = body.get('id')

    handler = _A2A_METHODS.get(method)
    if not handler:
        return JSONResponse({
            'jsonrpc': '2.0', 'id': req_id,
            'error': {'code': -32601, 'message': f'Unknown method: {method}'},
        })

    try:
        result = await handler(params, auth, db)
        return JSONResponse({'jsonrpc': '2.0', 'id': req_id, 'result': result})
    except Exception as e:
        logger.error(f'A2A error in {method}: {e}', exc_info=True)
        return JSONResponse({
            'jsonrpc': '2.0', 'id': req_id,
            'error': {'code': -32000, 'message': str(e)},
        })


# ── Method Handlers ──────────────────────────────────────────────

async def _tasks_send(params: dict, auth: AuthContext, db: Session) -> dict:
    """Submit a new task for execution."""
    from sajha.app import tools_registry, mcp_handler

    message = params.get('message', {})
    session_id = params.get('sessionId')
    text = ''

    # Extract text from message parts
    for part in message.get('parts', []):
        if part.get('type') == 'text':
            text += part.get('text', '')

    if not text:
        raise ValueError('No text content in message')

    # Create task record
    dao = A2ATaskDAO(db)
    task = A2ATask(
        session_id=session_id,
        state='working',
        input_message=json.dumps(message),
        caller_agent=auth.user_id or 'anonymous',
    )
    dao.create(task)

    # Try to match to a tool and execute
    # Simple strategy: look for tool name in the text, or use first tool mentioned
    result_text = ''
    matched_tool = None

    for tool_name in (tools_registry.tools.keys() if tools_registry else []):
        if tool_name.lower() in text.lower():
            matched_tool = tool_name
            break

    if matched_tool and tools_registry:
        tool = tools_registry.get_tool(matched_tool)
        if tool:
            try:
                result = tool.execute_with_tracking({})
                result_text = json.dumps(result) if isinstance(result, (dict, list)) else str(result)
                task.state = 'completed'
            except Exception as e:
                result_text = f'Tool execution failed: {e}'
                task.state = 'failed'
                task.error_message = str(e)
    else:
        # No specific tool matched — return capabilities
        result_text = (
            f"I'm {get_settings().app_name} with {len(tools_registry.tools) if tools_registry else 0} tools available. "
            f"Please specify a tool name to execute. Available tools include: "
            + ', '.join(list(tools_registry.tools.keys())[:20] if tools_registry else [])
        )
        task.state = 'completed'

    # Update task with result
    task.output_artifacts = json.dumps([{
        'parts': [{'type': 'text', 'text': result_text}],
    }])
    dao.update(task)

    return _task_to_response(task)


async def _tasks_get(params: dict, auth: AuthContext, db: Session) -> dict:
    """Get task status by ID."""
    task_id = params.get('id')
    if not task_id:
        raise ValueError('Task ID required')

    dao = A2ATaskDAO(db)
    task = dao.get_by_id(task_id)
    if not task:
        raise ValueError(f'Task {task_id} not found')

    return _task_to_response(task)


async def _tasks_cancel(params: dict, auth: AuthContext, db: Session) -> dict:
    """Cancel a running task."""
    task_id = params.get('id')
    if not task_id:
        raise ValueError('Task ID required')

    dao = A2ATaskDAO(db)
    task = dao.get_by_id(task_id)
    if not task:
        raise ValueError(f'Task {task_id} not found')

    if task.state in ('completed', 'failed', 'cancelled'):
        raise ValueError(f'Task already in terminal state: {task.state}')

    dao.update_state(task_id, 'cancelled')
    task = dao.get_by_id(task_id)
    return _task_to_response(task)


def _task_to_response(task: A2ATask) -> dict:
    """Convert A2ATask to A2A protocol response format."""
    result = {
        'id': task.id,
        'sessionId': task.session_id,
        'status': {
            'state': task.state,
            'timestamp': (task.updated_at or task.created_at).isoformat() + 'Z',
        },
    }

    if task.output_artifacts:
        try:
            result['artifacts'] = json.loads(task.output_artifacts)
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug(f"Handled: {e}")
            pass

    if task.error_message:
        result['status']['message'] = {
            'parts': [{'type': 'text', 'text': task.error_message}],
        }

    return result


_A2A_METHODS = {
    'tasks/send': _tasks_send,
    'tasks/get': _tasks_get,
    'tasks/cancel': _tasks_cancel,
}


# ═══════════════════════════════════════════════════
# MCP 2025-11-25: OAuth Discovery Endpoints
# ═══════════════════════════════════════════════════

@router.get('/.well-known/openid-configuration')
async def openid_configuration(request: Request):
    """MCP 2025-11-25 Major 1: OpenID Connect Discovery document."""
    from sajha.core.mcp_2025_11_25 import build_openid_configuration
    from sajha.core.config import get_settings
    _s = get_settings()
    server_url = f"{request.url.scheme}://{request.url.netloc}"
    return build_openid_configuration(server_url, server_url)


@router.get('/.well-known/oauth-protected-resource')
async def oauth_protected_resource(request: Request):
    """MCP 2025-11-25 Minor 8: Protected Resource Metadata per RFC 9728."""
    from sajha.core.mcp_2025_11_25 import build_protected_resource_metadata
    server_url = f"{request.url.scheme}://{request.url.netloc}"
    return build_protected_resource_metadata(server_url)


@router.get('/.well-known/oauth-client/{client_id}')
async def oauth_client_metadata(client_id: str, request: Request):
    """MCP 2025-11-25 Major 8: Client ID Metadata Document (CIMD)."""
    from sajha.core.mcp_2025_11_25 import build_client_id_metadata_document
    # Look up client from API keys or return default
    return build_client_id_metadata_document(
        client_id=client_id,
        client_name=f"SAJHA Client {client_id}",
        redirect_uris=[f"{request.url.scheme}://{request.url.netloc}/oauth/callback"]
    )
