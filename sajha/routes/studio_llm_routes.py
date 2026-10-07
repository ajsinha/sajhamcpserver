"""
SAJHA MCP Server — Studio "LLM tool" creator: the page and its JSON endpoints.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Needs the ``studio:llm`` permission (or ``studio:*``; admins always). A non-admin may change
only the LLM tools that record them as creator.

  GET  /studio/llm                         the page (?edit=<tool> opens an existing LLM tool)
  GET  /api/studio/llm/options             modes, model aliases, planners, prompts, ceilings
  GET  /api/studio/llm/tools               every LLM tool, with whether the caller may edit it
  GET  /api/studio/llm/tools/{name}        one LLM tool: its config and the form for it
  POST /admin/studio/llm/build             {form} -> {config, check}: the generated config, validated
  POST /admin/studio/llm/check             {config} -> check: a hand-edited config, validated
  POST /admin/studio/llm/match             {allow, deny, name?, nesting_allow?, confirm?} -> live matching
  POST /admin/studio/llm/test              {form | config, arguments, run_all?} -> one run against the mock model
  POST /admin/studio/llm/deploy            {form | config, edit?} -> written to config/tools and loaded

Served through studio_routes.router. Guide: docs/studio/MCP Studio LLM Tool Creator Guide.md.
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
actions = APIRouter(prefix='/admin/studio/llm', tags=['studio'])
reads = APIRouter(prefix='/api/studio/llm', tags=['studio'])
LLM = require_creator('llm')


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def _run(fn, *args, **kwargs) -> JSONResponse:
    from sajha.studio.llm_tool_builder import BuildError
    try:
        result = await run_in_threadpool(fn, *args, **kwargs)
    except BuildError as e:
        return JSONResponse({'success': False, 'error': str(e), **e.extra}, status_code=e.status)
    except Exception as e:
        logger.error(f'LLM tool creator failed: {e}', exc_info=True)
        return JSONResponse({'success': False, 'error': f'{e.__class__.__name__}: {e}'}, status_code=500)
    return JSONResponse({'success': True, **result})


def _config_of(data: Dict[str, Any]) -> Dict[str, Any]:
    from sajha.studio.llm_tool_builder import BuildError, build_config
    if isinstance(data.get('config'), dict):
        return data['config']
    if isinstance(data.get('form'), dict):
        return build_config(data['form'])
    raise BuildError('send {"form": {...}} or {"config": {...}}')


@pages.get('/llm')
async def studio_llm(request: Request, auth: AuthContext = Depends(LLM)):
    from sajha.studio import llm_tool_builder as b
    return render(request, 'admin/studio/studio_llm.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'llm_options': await run_in_threadpool(b.options),
        'edit_name': request.query_params.get('edit') or '',
    })


@reads.get('/options')
async def llm_options(auth: AuthContext = Depends(LLM)):
    from sajha.studio import llm_tool_builder as b
    return await _run(lambda: {'options': b.options()})


@reads.get('/tools')
async def llm_tools(auth: AuthContext = Depends(LLM)):
    from sajha.studio import llm_tool_builder as b
    return await _run(lambda: {'tools': b.list_tools(auth)})


@reads.get('/tools/{name}')
async def llm_tool(name: str, auth: AuthContext = Depends(LLM)):
    from sajha.auth import is_owner
    from sajha.studio import llm_tool_builder as b
    from sajha.studio.ownership import creator_of

    def load():
        cfg = b.existing(name)
        if cfg is None:
            raise b.BuildError(f'no LLM tool named {name}', 404)
        return {'config': cfg, 'form': b.form_from_config(cfg), 'editable': is_owner(auth, creator_of(cfg)),
                'created_by': creator_of(cfg) or None, 'check': b.check(cfg, editing=True)}
    return await _run(load)


@actions.post('/build')
async def llm_build(request: Request, auth: AuthContext = Depends(LLM)):
    from sajha.studio import llm_tool_builder as b
    data = await _body(request)

    def go():
        cfg = _config_of(data)
        return {'config': cfg, 'check': b.check(cfg, editing=bool(data.get('edit')))}
    return await _run(go)


@actions.post('/check')
async def llm_check(request: Request, auth: AuthContext = Depends(LLM)):
    from sajha.studio import llm_tool_builder as b
    data = await _body(request)
    return await _run(lambda: {'check': b.check(_config_of(data), editing=bool(data.get('edit')))})


@actions.post('/match')
async def llm_match(request: Request, auth: AuthContext = Depends(LLM)):
    from sajha.studio import llm_tool_builder as b
    data = await _body(request)
    return await _run(lambda: {'matching': b.match_preview(
        b._str_list(data.get('allow')), b._str_list(data.get('deny')), str(data.get('name') or ''),
        bool(data.get('nesting_allow')), str(data.get('confirm') or 'ask'))})


@actions.post('/test')
async def llm_test(request: Request, auth: AuthContext = Depends(LLM)):
    from sajha.studio import llm_tool_builder as b
    data = await _body(request)
    return await _run(lambda: {'run': b.test_run(_config_of(data), data.get('arguments') or {}, auth,
                                                 run_all=data.get('run_all') is True)})


@actions.post('/deploy')
async def llm_deploy(request: Request, auth: AuthContext = Depends(LLM)):
    from sajha.studio import llm_tool_builder as b
    data = await _body(request)
    return await _run(lambda: b.deploy(_config_of(data), auth, edit=bool(data.get('edit'))))


router = APIRouter()
router.include_router(pages)
router.include_router(actions)
router.include_router(reads)
