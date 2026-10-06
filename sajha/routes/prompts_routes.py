"""
SAJHA MCP Server v3 — Prompts Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import json
import re
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sajha.db.engine import get_db
from sajha.auth import require_auth, require_admin, AuthContext
from sajha.app import render

router = APIRouter(tags=['prompts'])


@router.get('/prompts')
async def prompts_list(request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import prompts_registry
    prompts = prompts_registry.get_all_prompts() if prompts_registry else []
    categories = prompts_registry.get_categories() if prompts_registry else []
    tags = prompts_registry.get_tags() if prompts_registry else []
    return render(request, 'prompts/prompts_list.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'prompts': prompts,
        'categories': categories,
        'tags': tags,
        'is_admin': auth.is_admin,
    })


@router.get('/prompts/create')
async def prompt_create_page(request: Request, auth: AuthContext = Depends(require_admin)):
    return render(request, 'prompts/prompt_create.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
    })


@router.get('/prompts/{prompt_name}')
async def prompt_detail(prompt_name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import prompts_registry
    prompt = prompts_registry.get_prompt(prompt_name) if prompts_registry else None
    if not prompt:
        return render(request, 'common/error.html', {
            'error': 'Prompt Not Found',
            'message': f'Prompt "{prompt_name}" does not exist',
        }, status_code=404)

    # The template reads usage_count/last_used under prompt.metadata and embeds the JSON
    # for its viewer and editor, so it needs the dict form, not the Prompt object
    prompt_data = prompt.to_dict()
    return render(request, 'prompts/prompt_detail.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'prompt': prompt_data,
        'prompt_json': json.dumps(prompt_data, indent=2),
        'prompt_name': prompt_name,
        'is_admin': auth.is_admin,
    })


@router.get('/prompts/{prompt_name}/test')
async def prompt_test(prompt_name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import prompts_registry
    prompt = prompts_registry.get_prompt(prompt_name) if prompts_registry else None
    if not prompt:
        return render(request, 'common/error.html', {
            'error': 'Prompt Not Found',
            'message': f'Prompt "{prompt_name}" does not exist',
        }, status_code=404)

    return render(request, 'prompts/prompt_test.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'prompt': prompt,
        'prompt_name': prompt_name,
        'is_admin': auth.is_admin,
    })


@router.get('/prompts/category/{category}')
async def prompts_by_category(category: str, request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import prompts_registry
    prompts = prompts_registry.get_prompts_by_category(category) if prompts_registry else []
    categories = prompts_registry.get_categories() if prompts_registry else []
    tags = prompts_registry.get_tags() if prompts_registry else []
    return render(request, 'prompts/prompts_list.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'prompts': prompts,
        'categories': categories,
        'tags': tags,
        'selected_category': category,
        'is_admin': auth.is_admin,
    })


@router.get('/prompts/tag/{tag}')
async def prompts_by_tag(tag: str, request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import prompts_registry
    prompts = prompts_registry.get_prompts_by_tag(tag) if prompts_registry else []
    categories = prompts_registry.get_categories() if prompts_registry else []
    tags = prompts_registry.get_tags() if prompts_registry else []
    return render(request, 'prompts/prompts_list.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'prompts': prompts,
        'categories': categories,
        'tags': tags,
        'selected_tag': tag,
        'is_admin': auth.is_admin,
    })


# ── Prompts API ──────────────────────────────────────────────────

async def _prompt_caller(request: Request, db: Session):
    """(session, error response) for the REST prompt catalog: the same gate as MCP
    ``prompts/list`` (401 where ``/mcp`` would answer one) and the same visibility
    (sajha/auth/access.py ``can_see_prompt``): every prompt for a signed-in caller,
    ``mcp.anonymous.prompts`` for an anonymous one."""
    from sajha.auth.oauth.resource_server import authorize_mcp
    auth, err = await authorize_mcp(request, db, 'prompts/list')
    if err is not None:
        return None, err
    return {'authenticated': bool(auth is not None and auth.authenticated)}, None


@router.get('/api/prompts/list')
async def api_prompts_list(request: Request, db: Session = Depends(get_db)):
    from sajha.app import prompts_registry
    from sajha.auth.access import can_see_prompt
    session, err = await _prompt_caller(request, db)
    if err is not None:
        return err
    prompts = prompts_registry.get_all_prompts() if prompts_registry else []
    prompts = [p for p in prompts if can_see_prompt(session, p.get('name'))]
    return JSONResponse({'prompts': prompts})


_PROMPT_NAME = re.compile(r'^[A-Za-z0-9_-]{1,100}$')


def _prompt_config(data: dict) -> dict:
    """The on-disk prompt config from what a page sends.

    The detail page's editor shows Prompt.to_dict(), where the text is 'template' and the
    metadata carries runtime fields (usage_count, last_used, timestamps); the create page
    sends the file format with 'prompt_template'. Both reduce to the file format.
    """
    meta = data.get('metadata') or {}
    return {
        'description': data.get('description', ''),
        'prompt_template': data.get('prompt_template', data.get('template')),
        'arguments': data.get('arguments') or [],
        'metadata': {k: meta[k] for k in ('category', 'tags', 'author', 'version') if k in meta},
    }


def _registry_result(result, status_code: int = 400) -> JSONResponse:
    """A registry (success, message) tuple as the JSON the pages expect."""
    ok, message = result
    if ok:
        return JSONResponse({'success': True, 'message': message})
    return JSONResponse({'success': False, 'error': message}, status_code=status_code)


@router.get('/api/prompts/{prompt_name}')
async def api_prompt_get(prompt_name: str, request: Request, db: Session = Depends(get_db)):
    from sajha.app import prompts_registry
    from sajha.auth.access import can_see_prompt
    session, err = await _prompt_caller(request, db)
    if err is not None:
        return err
    prompt = prompts_registry.get_prompt(prompt_name) if prompts_registry else None
    if not prompt or not can_see_prompt(session, prompt_name):   # hidden == missing
        return JSONResponse({'error': 'Prompt not found'}, status_code=404)
    return JSONResponse(prompt.to_dict())


@router.post('/api/prompts/create')
async def api_prompt_create(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.app import prompts_registry
    if not prompts_registry:
        return JSONResponse({'success': False, 'error': 'Prompts registry unavailable'}, status_code=503)
    data = await request.json()
    name = (data.get('name') or '').strip()
    # the name becomes a file name in the prompts store
    if not _PROMPT_NAME.match(name):
        return JSONResponse({'success': False, 'error': 'Name must be letters, digits, _ or - (max 100)'}, status_code=400)
    config = _prompt_config(data)
    if not config['prompt_template']:
        return JSONResponse({'success': False, 'error': "Missing 'prompt_template' field"}, status_code=400)
    return _registry_result(prompts_registry.create_prompt(name, config))


@router.post('/api/prompts/{prompt_name}/update')
async def api_prompt_update(prompt_name: str, request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.app import prompts_registry
    if not prompts_registry:
        return JSONResponse({'success': False, 'error': 'Prompts registry unavailable'}, status_code=503)
    if not prompts_registry.get_prompt(prompt_name):
        return JSONResponse({'success': False, 'error': f"Prompt '{prompt_name}' not found"}, status_code=404)
    config = _prompt_config(await request.json())
    if not config['prompt_template']:
        # without this, saving the editor's JSON would write a prompt with no text
        return JSONResponse({'success': False, 'error': "Missing 'template' field"}, status_code=400)
    return _registry_result(prompts_registry.update_prompt(prompt_name, config))


@router.post('/api/prompts/{prompt_name}/delete')
async def api_prompt_delete(prompt_name: str, auth: AuthContext = Depends(require_admin)):
    from sajha.app import prompts_registry
    if not prompts_registry:
        return JSONResponse({'success': False, 'error': 'Prompts registry unavailable'}, status_code=503)
    if not prompts_registry.get_prompt(prompt_name):
        return JSONResponse({'success': False, 'error': f"Prompt '{prompt_name}' not found"}, status_code=404)
    return _registry_result(prompts_registry.delete_prompt(prompt_name))


@router.post('/api/prompts/{prompt_name}/render')
async def api_prompt_render(prompt_name: str, request: Request, auth: AuthContext = Depends(require_auth)):
    from sajha.app import prompts_registry
    if not prompts_registry:
        return JSONResponse({'success': False, 'error': 'Prompts registry unavailable'}, status_code=503)
    if not prompts_registry.get_prompt(prompt_name):
        return JSONResponse({'success': False, 'error': f"Prompt '{prompt_name}' not found"}, status_code=404)
    data = await request.json()
    ok, out = prompts_registry.render_prompt(prompt_name, data.get('arguments') or {})
    if ok:
        return JSONResponse({'success': True, 'rendered': out})
    return JSONResponse({'success': False, 'error': out}, status_code=400)


@router.get('/admin/prompts')
async def admin_prompts(request: Request, auth: AuthContext = Depends(require_admin)):
    """Admin prompts management page."""
    from sajha.app import render, prompts_registry
    prompts = prompts_registry.get_all_prompts() if prompts_registry else []
    return render(request, 'admin/admin_prompts.html', {
        'prompts': prompts,
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
    })
