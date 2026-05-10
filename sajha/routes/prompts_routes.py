"""
SAJHA MCP Server v3 — Prompts Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import json
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

    return render(request, 'prompts/prompt_detail.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'prompt': prompt,
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

@router.get('/api/prompts/list')
async def api_prompts_list():
    from sajha.app import prompts_registry
    prompts = prompts_registry.get_all_prompts() if prompts_registry else []
    return JSONResponse({'prompts': prompts})


@router.get('/api/prompts/{prompt_name}')
async def api_prompt_get(prompt_name: str):
    from sajha.app import prompts_registry
    prompt = prompts_registry.get_prompt(prompt_name) if prompts_registry else None
    if not prompt:
        return JSONResponse({'error': 'Prompt not found'}, status_code=404)
    return JSONResponse(prompt)


@router.post('/api/prompts/create')
async def api_prompt_create(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.app import prompts_registry
    data = await request.json()
    result = prompts_registry.create_prompt(data) if prompts_registry else None
    if result:
        return JSONResponse({'success': True, 'prompt': result})
    return JSONResponse({'error': 'Failed to create prompt'}, status_code=400)
