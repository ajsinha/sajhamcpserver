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
async def agent_card(auth: AuthContext = Depends(get_current_user)):
    """
    A2A Agent Card — tells other agents what this server can do.

    The skills are the tools the caller may see (the tools/list policy,
    sajha/auth/access.py). A credential-less caller gets the anonymous policy
    (``mcp.anonymous.*``, by default nothing): a generic card with no tool inventory.
    """
    settings = get_settings()
    from sajha.app import tools_registry
    from sajha.auth.access import policy_for

    policy = policy_for(auth)

    # Build skills from the tools this caller may see
    skills = []
    if tools_registry:
        visible = [(n, t) for n, t in list(tools_registry.tools.items()) if policy.can_see(n)]
        for tool_name, tool in visible[:50]:
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

    Callers authenticate like the REST API (Bearer JWT, X-API-Key, session cookie).
    Without credentials the anonymous policy applies (mcp.anonymous.*), or 401 when
    mcp.anonymous.enabled is false.  A tool runs only if the caller may execute it
    (sajha/auth/access.py), and tasks are visible only to the caller that created them.
    """
    from sajha.auth.access import anonymous_enabled
    from sajha.auth.oauth.resource_server import presented_credentials
    if not auth.authenticated and presented_credentials(request):
        # credentials were sent but did not authenticate: refuse, never run as anonymous
        return JSONResponse({
            'jsonrpc': '2.0', 'id': None,
            'error': {'code': -32001, 'message': 'Invalid or expired credentials'},
        }, status_code=401, headers={'WWW-Authenticate': 'Bearer realm="sajha", error="invalid_token"'})
    if not auth.authenticated and not anonymous_enabled():
        return JSONResponse({
            'jsonrpc': '2.0', 'id': None,
            'error': {'code': -32001, 'message': 'Authentication required'},
        }, status_code=401, headers={'WWW-Authenticate': 'Bearer realm="sajha"'})
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
    from sajha.app import tools_registry
    from sajha.auth.access import policy_for
    policy = policy_for(auth)
    # who is calling, and through what, for the usage ledger and the policy engine
    from sajha.observability.caller import from_auth, set_caller
    from sajha.policy.context import set_source
    set_caller(from_auth(auth))
    set_source('a2a')

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
        caller_agent=_caller(auth),
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

    if matched_tool and tools_registry and not policy.can_execute(matched_tool):
        result_text = f'Access denied to tool: {matched_tool}'
        task.state = 'failed'
        task.error_message = result_text
    elif matched_tool and tools_registry:
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
        # No specific tool matched — return the capabilities this caller may use
        runnable = [n for n in (tools_registry.tools.keys() if tools_registry else [])
                    if policy.can_execute(n)]
        result_text = (
            f"I'm {get_settings().app_name} with {len(runnable)} tools available to you. "
            f"Please specify a tool name to execute. Available tools include: "
            + ', '.join(runnable[:20])
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
    if not task or not _owns(auth, task):
        raise ValueError(f'Task {task_id} not found')

    return _task_to_response(task)


async def _tasks_cancel(params: dict, auth: AuthContext, db: Session) -> dict:
    """Cancel a running task."""
    task_id = params.get('id')
    if not task_id:
        raise ValueError('Task ID required')

    dao = A2ATaskDAO(db)
    task = dao.get_by_id(task_id)
    if not task or not _owns(auth, task):
        raise ValueError(f'Task {task_id} not found')

    if task.state in ('completed', 'failed', 'cancelled'):
        raise ValueError(f'Task already in terminal state: {task.state}')

    dao.update_state(task_id, 'cancelled')
    task = dao.get_by_id(task_id)
    return _task_to_response(task)


def _caller(auth: AuthContext) -> str:
    return (auth.user_id if auth.authenticated else None) or 'anonymous'


def _owns(auth: AuthContext, task: A2ATask) -> bool:
    """Admins see every task; anyone else only the tasks they submitted."""
    return bool(auth.authenticated and auth.is_admin) or task.caller_agent == _caller(auth)


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
# OAuth discovery
# ═══════════════════════════════════════════════════
# /.well-known/openid-configuration, /.well-known/oauth-protected-resource and
# /.well-known/oauth-client/{id} are intentionally NOT served: SAJHA does not
# run an OAuth authorization server, and the documents previously served here
# advertised /oauth/* endpoints that never existed.  /mcp authenticates with
# SAJHA JWTs or API keys (Authorization: Bearer / X-API-Key); MCP clients
# treat a 404 on the protected-resource metadata URL as "no OAuth".
