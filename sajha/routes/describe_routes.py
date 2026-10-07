"""
SAJHA MCP Server — Studio "Describe a tool": the page and its JSON endpoints (MCP Studio access:
admin, or a role with the studio permission).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

  GET  /studio/describe                         the page
  POST /admin/studio/describe/propose           description -> validated proposal, files, policy (a draft)
  POST /admin/studio/describe/revise            an edited proposal -> validated again (new hash)
  POST /admin/studio/describe/test              run the draft's test cases (sandbox / fixtures)
  POST /admin/studio/describe/deploy            deploy the reviewed hash (approve: true)
  GET  /api/studio/describe/drafts/{id}         a draft (JSON)

Served through studio_routes.router. Design: docs/architecture/Tool Generation.md.
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
actions = APIRouter(prefix='/admin/studio/describe', tags=['studio'])
reads = APIRouter(prefix='/api/studio/describe', tags=['studio'])


async def _body(request: Request) -> Dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


async def _run(fn, *args, **kwargs) -> JSONResponse:
    from sajha.studio.describe import DescribeError
    try:
        result = await run_in_threadpool(fn, *args, **kwargs)
    except DescribeError as e:
        return JSONResponse({'success': False, 'error': str(e), **e.extra}, status_code=e.status)
    except Exception as e:
        logger.error(f'describe a tool failed: {e}', exc_info=True)
        return JSONResponse({'success': False, 'error': f'{e.__class__.__name__}: {e}'}, status_code=500)
    return JSONResponse({'success': True, **result})


@pages.get('/describe')
async def studio_describe(request: Request, auth: AuthContext = Depends(require_creator('describe'))):
    from sajha.studio import describe
    try:
        from sajha.sandbox import studio_policy
        sandbox = studio_policy()
    except Exception:
        sandbox = None
    return render(request, 'admin/studio/studio_describe.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'enabled': describe.enabled(),
        'model_alias': describe.model_alias(),
        'max_chars': describe.max_description_chars(),
        'kinds': describe.KINDS,
        'sandbox': sandbox,
    })


@actions.post('/propose')
async def describe_propose(request: Request, auth: AuthContext = Depends(require_creator('describe'))):
    from sajha.studio import describe
    data = await _body(request)
    return await _run(describe.propose, str(data.get('description') or ''), str(data.get('kind') or 'auto'), auth)


@actions.post('/revise')
async def describe_revise(request: Request, auth: AuthContext = Depends(require_creator('describe'))):
    from sajha.studio import describe
    data = await _body(request)
    return await _run(describe.revise, str(data.get('draft_id') or ''), data.get('proposal'), auth)


@actions.post('/test')
async def describe_test(request: Request, auth: AuthContext = Depends(require_creator('describe'))):
    from sajha.studio import describe
    data = await _body(request)
    return await _run(describe.run_tests, str(data.get('draft_id') or ''), bool(data.get('live')), auth)


@actions.post('/deploy')
async def describe_deploy(request: Request, auth: AuthContext = Depends(require_creator('describe'))):
    from sajha.studio import describe
    data = await _body(request)
    return await _run(describe.deploy, str(data.get('draft_id') or ''), str(data.get('hash') or ''),
                      data.get('approve') is True, data.get('accept_failures') is True, auth)


@reads.get('/drafts/{draft_id}')
async def describe_draft(draft_id: str, auth: AuthContext = Depends(require_creator('describe'))):
    from sajha.studio import describe
    return await _run(lambda: describe.public(describe.get_draft(draft_id, auth)))


router = APIRouter()
router.include_router(pages)
router.include_router(actions)
router.include_router(reads)
