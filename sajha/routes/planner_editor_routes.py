"""
SAJHA MCP Server — Studio planner editor: the page and its JSON endpoints (administrators only,
LLM Tools §9.10 decision 6: a planner decides how much every tool that uses it may spend).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

  GET  /studio/planners                      the page
  GET  /api/studio/planners                  planners, versions, refused files and their load problems
  GET  /api/studio/planners/{ref}            one planner file (name or name@version): text, check, graph
  POST /admin/studio/planners/check          {text} -> schema and P-rule diagnostics, the graph
  POST /admin/studio/planners/save           {text} -> a new version written to config/planners

The page's dry run posts to ``POST /api/ai/planners/dry-run`` (sajha/routes/ai_routes.py).
Served through studio_routes.router. Reference: docs/architecture/Planner Reference.md §14.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from sajha.app import render
from sajha.auth import AuthContext, require_creator

logger = logging.getLogger(__name__)

pages = APIRouter(prefix='/studio', tags=['studio'])
actions = APIRouter(prefix='/admin/studio/planners', tags=['studio'])
reads = APIRouter(prefix='/api/studio/planners', tags=['studio'])
PLANNER = require_creator('planner')


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def _run(fn, *args, **kwargs) -> JSONResponse:
    from sajha.studio.planner_editor import EditorError
    try:
        result = await run_in_threadpool(fn, *args, **kwargs)
    except EditorError as e:
        return JSONResponse({'success': False, 'error': str(e), **e.extra}, status_code=e.status)
    except Exception as e:
        logger.error(f'planner editor failed: {e}', exc_info=True)
        return JSONResponse({'success': False, 'error': f'{e.__class__.__name__}: {e}'}, status_code=500)
    return JSONResponse({'success': True, **result})


@pages.get('/planners')
async def studio_planners(request: Request, auth: AuthContext = Depends(PLANNER)):
    from sajha.studio import planner_editor
    data = await run_in_threadpool(planner_editor.listing)
    return render(request, 'admin/studio/studio_planners.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'planner_data': data,
        'open_ref': request.query_params.get('open') or '',
    })


@reads.get('')
async def planners_list(auth: AuthContext = Depends(PLANNER)):
    from sajha.studio import planner_editor
    return await _run(planner_editor.listing)


@reads.get('/{ref}')
async def planner_source(ref: str, auth: AuthContext = Depends(PLANNER)):
    from sajha.studio import planner_editor
    return await _run(planner_editor.source, ref)


@actions.post('/check')
async def planner_check(request: Request, auth: AuthContext = Depends(PLANNER)):
    from sajha.studio import planner_editor
    data = await _body(request)
    return await _run(planner_editor.check, str(data.get('text') or ''))


@actions.post('/save')
async def planner_save(request: Request, auth: AuthContext = Depends(PLANNER)):
    from sajha.studio import planner_editor
    data = await _body(request)
    return await _run(planner_editor.save, str(data.get('text') or ''), auth.user_id or '')


router = APIRouter()
router.include_router(pages)
router.include_router(actions)
router.include_router(reads)
