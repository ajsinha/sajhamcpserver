"""
SAJHA MCP Server — the OpenAI-compatible endpoint: /v1/chat/completions, /v1/models, /v1/embeddings.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Opt-in (``ai.openai_api.enabled``); turned off, every /v1 route answers 404. The logic is in
sajha/ai/openai_api.py; design and as-built: docs/architecture/LLM Tools.md §13.4.
"""

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from sajha.ai import openai_api as api
from sajha.db.engine import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=['openai'])


def _error(e: Exception, model: str = '') -> JSONResponse:
    err = api.error_for(e, model)
    return JSONResponse(err.body(), status_code=err.status, headers=err.headers())


def _caller(request: Request, db: Session = Depends(get_db)):
    """(AuthContext or None, error response or None): the surface must be on and the caller known."""
    if not api.enabled():
        return None, _error(api.APIError(404, 'The OpenAI-compatible API is turned off (ai.openai_api.enabled).',
                                         type='not_found_error', code='not_found'))
    auth = api.authenticate(request, db)
    if auth is None:
        err = api.APIError(401, 'Incorrect or missing API key: send a SAJHA API key as "Authorization: Bearer '
                                'sja_..."', type='invalid_request_error', code='invalid_api_key')
        return None, JSONResponse(err.body(), status_code=401, headers={'WWW-Authenticate': 'Bearer realm="sajha"'})
    return auth, None


async def _json(request: Request):
    s = api.settings()
    raw = await request.body()
    if s is not None and len(raw) > s.max_body_bytes:
        raise api.APIError(413, f'the request body is larger than ai.openai_api.max_body_bytes ({s.max_body_bytes})',
                           code='request_too_large')
    try:
        return json.loads(raw or b'null')
    except ValueError:
        raise api.APIError(400, 'the request body is not valid JSON')


def _sse(obj) -> str:
    return f'data: {json.dumps(obj, default=str)}\n\n'


@router.get('/v1/models')
async def v1_models(caller=Depends(_caller)):
    auth, err = caller
    if err is not None:
        return err
    try:
        return JSONResponse(await run_in_threadpool(api.list_models, auth))
    except Exception as e:
        return _error(e)


@router.get('/v1/models/{model_id:path}')
async def v1_model(model_id: str, caller=Depends(_caller)):
    auth, err = caller
    if err is not None:
        return err
    try:
        return JSONResponse(await run_in_threadpool(api.get_model, model_id, auth))
    except Exception as e:
        return _error(e, model_id)


@router.post('/v1/embeddings')
async def v1_embeddings(request: Request, caller=Depends(_caller)):
    auth, err = caller
    if err is not None:
        return err
    model = ''
    try:
        body = await _json(request)
        model = body.get('model', '') if isinstance(body, dict) else ''

        def work():
            api.bind_caller(auth)
            api.check_policy(api.EMBEDDINGS_PSEUDO_TOOL, str(model))
            return api.embeddings(body, auth)

        out = await run_in_threadpool(work)
        api.audit(auth, 'embeddings', model, 'ok', tokens=(out.get('usage') or {}).get('total_tokens'))
        return JSONResponse(out)
    except Exception as e:
        api.audit(auth, 'embeddings', model, 'error', error=str(e)[:300])
        return _error(e, model)


@router.post('/v1/chat/completions')
async def v1_chat_completions(request: Request, caller=Depends(_caller)):
    from sajha.ai.llm.canonical import completion_to_chunks
    auth, err = caller
    if err is not None:
        return err
    model = ''
    try:
        body, extra = api.split_body(await _json(request))
        model = body['model']
        stream = bool(body.get('stream'))
        include_usage = bool((body.get('stream_options') or {}).get('include_usage')) if isinstance(
            body.get('stream_options'), dict) else False

        if model.startswith(api.TOOL_PREFIX):          # an LLM tool as a model: run it as the caller
            def run():
                api.bind_caller(auth)
                api.check_policy(api.CHAT_PSEUDO_TOOL, model)
                tool, args, model_id, ignored = api.tool_request(body, extra, auth)
                return api.run_tool(tool, args, auth, model_id, ignored)

            comp = await run_in_threadpool(run)
            api.audit(auth, 'chat.completions', model, 'ok', stopped_by=getattr(comp.sajha, 'stopped_by', None),
                      conversation_id=getattr(comp.sajha, 'conversation_id', None))
            if not stream:
                return JSONResponse(comp.to_dict())
            chunks = [c.to_dict() for c in completion_to_chunks(comp, include_usage=include_usage)]
            return StreamingResponse(iter([_sse(c) for c in chunks] + ['data: [DONE]\n\n']),
                                     media_type='text/event-stream', headers={'Cache-Control': 'no-cache'})

        def prepare():
            api.bind_caller(auth)
            api.check_policy(api.CHAT_PSEUDO_TOOL, model)
            return api.prepare_chat(body, auth)

        req = await run_in_threadpool(prepare)
        if not stream:
            comp = await run_in_threadpool(api.chat_create, req)
            u = comp.usage
            api.audit(auth, 'chat.completions', model, 'ok', served_by=comp.sajha.qualified_model if comp.sajha else '',
                      tokens=u.total_tokens if u else 0, cost_usd=comp.sajha.cost_usd if comp.sajha else 0.0)
            return JSONResponse(comp.to_dict())

        gen = api.chat_stream(req)
        first = await run_in_threadpool(next, gen, None)      # errors before the first chunk are HTTP errors
        api.audit(auth, 'chat.completions', model, 'ok', stream=True)

        def events():
            if first is not None:
                yield _sse(first.to_dict())
                try:
                    for c in gen:
                        yield _sse(c.to_dict())
                except Exception as e:     # mid-stream: an error event the OpenAI SDKs raise, then the end
                    yield _sse(api.error_for(e, model).body())
            yield 'data: [DONE]\n\n'

        return StreamingResponse(events(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    except Exception as e:
        api.audit(auth, 'chat.completions', model, 'error', error=str(e)[:300])
        return _error(e, model)
