"""
SAJHA MCP Server v3 — AI Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Admin UI + API for LLM provider management, model selection,
user preferences, token usage, and semantic tool resolution.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from sajha.auth import AuthContext, require_auth, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(tags=['ai'])


def _get_gateway():
    """The process-wide LLM factory (sajha.ai.llm), or None before the intelligence layer starts."""
    from sajha.ai.llm import llm_factory
    return llm_factory()


def _get_resolver():
    from sajha.ai.tool_resolver import get_resolver
    return get_resolver()


from sajha.db.engine import get_db
from sqlalchemy.orm import Session


# ── Admin: Provider Management (DB-driven) ───────────────────

@router.get('/api/ai/providers')
async def api_list_providers(auth: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    """List all LLM providers from database with health status."""
    from sajha.db.dao import LLMProviderDAO, LLMModelDAO
    gw = _get_gateway()

    provider_dao = LLMProviderDAO(db)
    model_dao = LLMModelDAO(db)

    providers = []
    for p in provider_dao.get_all_enabled():
        models = [{'model_id': m.model_id, 'display_name': m.display_name,
                    'context_window': m.context_window, 'input_cost_per_1k': m.input_cost_per_1k,
                    'output_cost_per_1k': m.output_cost_per_1k, 'supports_tools': m.supports_tools,
                    'supports_vision': m.supports_vision, 'supports_embeddings': m.supports_embeddings,
                    'tags': m.tags or '', 'is_default': m.is_default, 'enabled': m.enabled,
                   } for m in model_dao.get_by_provider(p.provider_type, enabled_only=False)]

        healthy = False
        if gw and gw.provider(p.provider_type) and gw.provider(p.provider_type).active:
            try:
                healthy = gw.provider_health(p.provider_type).ok
            except Exception as e:
                logger.warning(f"Error handled: {e}", exc_info=True)

        providers.append({
            'type': p.provider_type, 'display_name': p.display_name,
            'enabled': p.enabled, 'is_default': p.is_default,
            'has_api_key': bool(p.api_key), 'base_url': p.base_url or '',
            'healthy': healthy, 'models': models, 'model_count': len(models),
        })

    default_prov = provider_dao.get_default()
    default_model_rec = model_dao.get_default_for_provider(default_prov.provider_type) if default_prov else None

    return JSONResponse({
        'providers': providers,
        'default_provider': default_prov.provider_type if default_prov else '',
        'default_model': default_model_rec.model_id if default_model_rec else '',
    })


@router.get('/api/ai/models')
async def api_list_all_models(auth: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    """List all models from database."""
    from sajha.db.dao import LLMModelDAO
    dao = LLMModelDAO(db)
    models = [{'id': m.id, 'provider_type': m.provider_type, 'model_id': m.model_id,
               'display_name': m.display_name, 'context_window': m.context_window,
               'max_output_tokens': m.max_output_tokens,
               'input_cost_per_1k': m.input_cost_per_1k, 'output_cost_per_1k': m.output_cost_per_1k,
               'supports_tools': m.supports_tools, 'supports_vision': m.supports_vision,
               'supports_embeddings': m.supports_embeddings,
               'tags': m.tags or '', 'is_default': m.is_default, 'enabled': m.enabled,
              } for m in dao.get_all_enabled()]
    return JSONResponse({'models': models})


@router.post('/api/ai/providers/{provider_type}/config')
async def api_update_provider(provider_type: str, request: Request,
                               auth: AuthContext = Depends(require_admin),
                               db: Session = Depends(get_db)):
    """Update provider configuration (API key, base URL, enabled)."""
    from sajha.db.dao import LLMProviderDAO
    data = await request.json()
    dao = LLMProviderDAO(db)
    p = dao.update_config(
        provider_type,
        api_key=data.get('api_key'),
        base_url=data.get('base_url'),
        region=data.get('region'),
        enabled=data.get('enabled'),
    )
    if not p:
        return JSONResponse({'error': 'Provider not found'}, status_code=404)
    return JSONResponse({'success': True, 'provider_type': p.provider_type})


@router.post('/api/ai/providers/{provider_type}/health')
async def api_provider_health(provider_type: str, auth: AuthContext = Depends(require_admin)):
    """Health check a specific provider."""
    gw = _get_gateway()
    if not gw:
        return JSONResponse({'error': 'Gateway not initialized'}, status_code=503)
    prov = gw.provider(provider_type)
    if not prov:
        return JSONResponse({'error': f'Provider {provider_type} not registered'}, status_code=404)
    h = gw.provider_health(provider_type, refresh=True)
    return JSONResponse({'provider': provider_type, 'healthy': h.ok and prov.active,
                         'active': prov.active, 'status': h.status, 'detail': h.detail})


@router.post('/api/ai/defaults')
async def api_set_defaults(request: Request, auth: AuthContext = Depends(require_admin),
                            db: Session = Depends(get_db)):
    """Set system-wide default provider and model (persisted to DB)."""
    from sajha.db.dao import LLMProviderDAO, LLMModelDAO
    data = await request.json()
    prov_dao = LLMProviderDAO(db)
    model_dao = LLMModelDAO(db)

    if 'provider' in data:
        prov_dao.set_default(data['provider'])
    if 'model' in data and 'provider' in data:
        model_dao.set_default(data['provider'], data['model'])

    # Also update the in-memory gateway: provider[/model] goes first in the 'default' alias
    gw = _get_gateway()
    if gw and data.get('provider'):
        gw.set_system_default(data['provider'], data.get('model', ''))

    return JSONResponse({'success': True})


# ── Admin: Model CRUD ─────────────────────────────────────────

@router.post('/api/ai/models')
async def api_create_model(request: Request, auth: AuthContext = Depends(require_admin),
                            db: Session = Depends(get_db)):
    """Create a new model entry."""
    from sajha.db.dao import LLMModelDAO
    data = await request.json()
    dao = LLMModelDAO(db)
    m = dao.create_model(
        provider_type=data['provider_type'], model_id=data['model_id'],
        display_name=data.get('display_name', data['model_id']),
        context_window=int(data.get('context_window', 0)),
        max_output_tokens=int(data.get('max_output_tokens', 4096)),
        input_cost_per_1k=float(data.get('input_cost_per_1k', 0)),
        output_cost_per_1k=float(data.get('output_cost_per_1k', 0)),
        supports_tools=data.get('supports_tools', True),
        supports_vision=data.get('supports_vision', False),
        supports_embeddings=data.get('supports_embeddings', False),
        tags=data.get('tags', ''),
    )
    return JSONResponse({'success': True, 'model_id': m.model_id})


@router.put('/api/ai/models/{model_id}')
async def api_update_model(model_id: str, request: Request,
                            auth: AuthContext = Depends(require_admin),
                            db: Session = Depends(get_db)):
    """Update model properties."""
    from sajha.db.dao import LLMModelDAO
    data = await request.json()
    dao = LLMModelDAO(db)
    m = dao.update_model(model_id, **data)
    if not m:
        return JSONResponse({'error': 'Model not found'}, status_code=404)
    return JSONResponse({'success': True})


@router.delete('/api/ai/models/{model_id}')
async def api_delete_model(model_id: str, auth: AuthContext = Depends(require_admin),
                            db: Session = Depends(get_db)):
    """Delete a model entry."""
    from sajha.db.dao import LLMModelDAO
    if LLMModelDAO(db).delete_model(model_id):
        return JSONResponse({'success': True})
    return JSONResponse({'error': 'Model not found'}, status_code=404)


# ── User: AI Preferences ─────────────────────────────────────

@router.get('/api/ai/preferences')
async def api_get_preferences(auth: AuthContext = Depends(require_auth)):
    """Get current user's AI preferences."""
    gw = _get_gateway()
    if not gw:
        return JSONResponse({'preferences': {}})
    pref = gw.get_user_preference(auth.user_id)
    return JSONResponse({
        'user_id': auth.user_id,
        'preferences': pref,
        'system_defaults': {
            'provider': gw.config.default_provider,
            'model': gw.config.default_model,
        },
        'effective': {
            'provider': pref.get('provider', gw.config.default_provider),
            'model': pref.get('model', gw.config.default_model),
        },
    })


@router.post('/api/ai/preferences')
async def api_set_preferences(request: Request, auth: AuthContext = Depends(require_auth)):
    """Set current user's AI preferences (overrides system defaults)."""
    gw = _get_gateway()
    if not gw:
        return JSONResponse({'error': 'Gateway not initialized'}, status_code=503)
    data = await request.json()
    gw.set_user_preference(
        auth.user_id,
        provider=data.get('provider', ''),
        model=data.get('model', ''),
        temperature=float(data.get('temperature', 0)),
        max_tokens=int(data.get('max_tokens', 0)),
    )
    return JSONResponse({'success': True, 'preferences': gw.get_user_preference(auth.user_id)})


@router.delete('/api/ai/preferences')
async def api_clear_preferences(auth: AuthContext = Depends(require_auth)):
    """Clear user preferences, revert to system defaults."""
    gw = _get_gateway()
    if gw:
        gw.clear_user_preference(auth.user_id)
    return JSONResponse({'success': True})


# ── Token Usage & Budget ─────────────────────────────────────

@router.get('/api/ai/usage')
async def api_get_usage(auth: AuthContext = Depends(require_auth)):
    """Get token usage for the current user."""
    gw = _get_gateway()
    if not gw:
        return JSONResponse({'usage': {}, 'total_cost': 0})
    return JSONResponse({
        'user_id': auth.user_id,
        'usage': gw.get_token_usage(auth.user_id),
        'total_cost_usd': round(gw.get_total_cost(auth.user_id), 6),
    })


@router.get('/api/ai/usage/all')
async def api_get_all_usage(auth: AuthContext = Depends(require_admin)):
    """Get token usage across all users (admin only)."""
    gw = _get_gateway()
    if not gw:
        return JSONResponse({'usage': {}})
    return JSONResponse({'usage': gw.get_token_usage(), 'cache': gw.cache_stats()})


# ── Semantic Tool Resolution (Phase 2) ───────────────────────

@router.post('/api/ai/resolve-tool')
async def api_resolve_tool(request: Request, auth: AuthContext = Depends(require_auth)):
    """Resolve natural language intent to matching SAJHA tools."""
    resolver = _get_resolver()
    if not resolver:
        return JSONResponse({'error': 'Tool resolver not initialized'}, status_code=503)
    data = await request.json()
    query = data.get('query', '')
    top_k = int(data.get('top_k', 5))
    extract_params = data.get('extract_params', False)

    if not query:
        return JSONResponse({'error': 'query is required'}, status_code=400)

    matches = resolver.resolve(query, top_k=top_k, extract_params=extract_params)
    return JSONResponse({
        'query': query,
        'matches': [m.to_dict() for m in matches],
        'count': len(matches),
        'index_stats': resolver.stats(),
    })


@router.post('/api/ai/resolve-tool/rebuild')
async def api_rebuild_index(auth: AuthContext = Depends(require_admin)):
    """Rebuild the semantic tool embedding index."""
    resolver = _get_resolver()
    if not resolver:
        return JSONResponse({'error': 'Resolver not initialized'}, status_code=503)
    count = resolver.build_index()
    return JSONResponse({'success': True, 'indexed_tools': count})


# ── LLM Completion (direct gateway access) ───────────────────

@router.post('/api/ai/complete')
async def api_complete(request: Request, auth: AuthContext = Depends(require_auth)):
    """Send a completion request through the LLM gateway."""
    gw = _get_gateway()
    if not gw:
        return JSONResponse({'error': 'Gateway not initialized'}, status_code=503)
    data = await request.json()
    prompt = data.get('prompt', '')
    if not prompt:
        return JSONResponse({'error': 'prompt is required'}, status_code=400)

    from sajha.ai.llm import ChatMessage, RequestContext
    try:
        ctx = RequestContext(user_id=auth.user_id or '', roles=list(auth.roles or []), is_admin=auth.is_admin)
        model = gw.model(gw.qualify(data.get('provider', ''), data.get('model', '')), context=ctx)
        messages = ([ChatMessage.system(data['system'])] if data.get('system') else []) + [ChatMessage.user(prompt)]
        max_tokens = int(data.get('max_tokens', 0) or 0)
        c = model.chat_completions_create(messages=messages, temperature=float(data.get('temperature', 0)),
                                          max_completion_tokens=max_tokens or None)
        u, sj = c.usage, c.sajha
        return JSONResponse({
            'content': c.text,
            'model': c.model,
            'provider': sj.provider if sj else '',
            'tokens': {'input': u.prompt_tokens if u else 0, 'output': u.completion_tokens if u else 0,
                       'total': u.total_tokens if u else 0},
            'cost_usd': round(sj.cost_usd if sj else 0.0, 6),
            'latency_ms': sj.latency_ms if sj else 0,
        })
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)


# ── Gateway Stats ────────────────────────────────────────────

@router.get('/api/ai/stats')
async def api_ai_stats(auth: AuthContext = Depends(require_admin)):
    """Get AI gateway statistics."""
    gw = _get_gateway()
    resolver = _get_resolver()
    stats = {}
    if gw:
        stats['gateway'] = gw.get_stats()
    if resolver:
        stats['resolver'] = resolver.stats()
    return JSONResponse(stats)


# ── Web UI Page ──────────────────────────────────────────────

from sajha.app import render

@router.get('/ai/settings')
async def ai_settings_page(request: Request, auth: AuthContext = Depends(require_auth)):
    """AI settings page — provider management, preferences, tool discovery."""
    return render(request, 'ai/ai_settings.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
    })


#: Ask SAJHA's example chips. Each is answered by the mock planner (the default model) from the
#: offline calc_* tools, so they work with no keys; tests/test_ask_page.py runs every one.
ASK_EXAMPLES = [
    'What is the percentage change from 80 to 100?',
    'What is the price of a bond with face value 1000, coupon rate 5, yield 4.5 over 10 years?',
    'What is the future value of 5000 at 7 percent for 20 years?',
    'Compare the Sharpe ratio and Sortino ratio for a return of 12 with risk free rate 4 and volatility 15',
]


def _tool_blurbs(limit: int = 120, visible=None) -> dict:
    """{tool name: its description's first line, clipped}: the sky's hover tooltips
    (only the tools ``visible(name)`` allows, when given)."""
    from sajha.app import tools_registry
    out = {}
    for name, tool in (getattr(tools_registry, 'tools', None) or {}).items():
        if visible is not None and not visible(name):
            continue
        try:
            d = str(getattr(tool, 'description', '') or '').strip().split('\n')[0]
        except Exception:
            d = ''
        if d:
            out[name] = d if len(d) <= limit else d[:limit - 1].rstrip() + '…'
    return out



def _local_server_name() -> str:
    """The name the Ask page shows for this server in its calls log: the SAJHA Net instance name
    when one is configured, otherwise the host name."""
    import socket
    from sajha.core.config import _get
    name = _get('sajhanet.instance_name', '') or ''
    return str(name) or socket.gethostname()


@router.get('/ask')
async def ask_page(request: Request, auth: AuthContext = Depends(require_auth)):
    """Ask SAJHA: a chat over POST /api/ai/ask, with the tool chain drawn live on the catalog's sky."""
    from sajha.web.help_catalog import live_tool_groups
    from sajha.ai.intelligence import get_intelligence
    from sajha.auth.access import policy_for
    svc = get_intelligence()
    can_see = policy_for(auth).can_see       # name only the tools tools/list shows this user
    live = live_tool_groups(with_names=True, visible=can_see)
    return render(request, 'ai/ask.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'ask_data': {
            'groups': [[g['name'], g['tool_count'], g['tools']] for g in live['groups']],
            'total': live['total_tools'],
            'descriptions': _tool_blurbs(visible=can_see),
            'examples': ASK_EXAMPLES,
            'server_name': _local_server_name(),
            'is_admin': bool(auth.is_admin),
            'enabled': bool(svc is not None and svc.settings.enabled),
            'user': auth.user_id or '',
        },
    })


# ── Provider Registry Info ────────────────────────────────────

@router.get('/api/ai/registry')
async def api_registry(auth: AuthContext = Depends(require_admin)):
    """List all registered provider classes (available to configure)."""
    from sajha.ai.llm import LLMFactory
    return JSONResponse({
        'registered_types': LLMFactory.provider_types(),
        'legacy_types': LLMFactory.legacy_provider_types(),
        'info': 'Add a provider with @register_provider, a class path in ai.providers, or a '
                "'sajha.llm_providers' entry point; see docs/architecture/Intelligence Layer.md",
    })


# ── Intelligence layer: effective configuration and ask ───────

@router.get('/api/ai/config')
async def api_ai_config(auth: AuthContext = Depends(require_admin)):
    """Effective ai.* configuration: every setting with its source (default/config/env/db), secrets redacted."""
    gw = _get_gateway()
    if not gw:
        return JSONResponse({'error': 'Gateway not initialized'}, status_code=503)
    from starlette.concurrency import run_in_threadpool
    return JSONResponse(await run_in_threadpool(gw.describe_config))


def _sse(event: dict) -> str:
    return f"id: {event.get('seq', '')}\nevent: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"


@router.post('/api/ai/ask')
async def api_ask(request: Request, auth: AuthContext = Depends(require_auth)):
    """Answer a question with SAJHA's tools. JSON AskResult, or an SSE step stream when the client
    sends Accept: text/event-stream or ?stream=1. Body: {question, model?, confirm?: [fingerprint],
    conversation_id?: "new" | id, planner?: name (admins)}."""
    from starlette.concurrency import run_in_threadpool
    from fastapi.responses import StreamingResponse
    from sajha.ai.intelligence import get_intelligence
    from sajha.ai.llm import RequestContext
    svc = get_intelligence()
    if svc is None:
        return JSONResponse({'error': 'Intelligence service not initialized'}, status_code=503)
    if not svc.settings.enabled:
        return JSONResponse({'error': 'ai.ask is disabled'}, status_code=403)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({'error': 'body must be JSON: {"question": "..."}'}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({'error': 'body must be a JSON object'}, status_code=400)
    question = str(data.get('question') or '').strip()
    if not question:
        return JSONResponse({'error': 'question is required'}, status_code=400)
    if len(question) > 8000:
        return JSONResponse({'error': 'question is too long (max 8000 characters)'}, status_code=400)
    model = data.get('model') or None
    if model is not None and not isinstance(model, str):
        return JSONResponse({'error': 'model must be a string (an alias or provider/model)'}, status_code=400)
    confirm = [str(c) for c in (data.get('confirm') or []) if c] if isinstance(data.get('confirm'), list) else []
    # conversation memory: "new" starts a conversation, an id continues one of this user's
    conversation_id = data.get('conversation_id') or None
    if conversation_id is not None:
        from sajha.ai.memory import NEW, valid_id
        if not isinstance(conversation_id, str) or not (conversation_id == NEW or valid_id(conversation_id)):
            return JSONResponse({'error': 'conversation_id must be "new" or a conversation id'}, status_code=400)
        if not auth.user_id:
            return JSONResponse({'error': 'conversations belong to signed-in users'}, status_code=400)
        if conversation_id != NEW:
            try:
                found = await run_in_threadpool(lambda: svc.memory.exists(conversation_id, auth.user_id))
            except Exception as e:
                logger.warning(f'conversation memory unavailable: {e}')
                found = True       # the service answers without memory and says so in a caveat
            if not found:
                return JSONResponse({'error': 'conversation not found'}, status_code=404)
    # the planning strategy for this ask (admins only): a registered name or package.module:Class
    planner = data.get('planner') or None
    if planner is not None:
        if not auth.is_admin:
            return JSONResponse({'error': 'only administrators may choose the planner'}, status_code=403)
        from sajha.ai.planners_engine import get_registry
        try:
            get_registry().compiled(planner if isinstance(planner, dict) else str(planner))
        except Exception as e:
            return JSONResponse({'error': str(e)[:300]}, status_code=400)

    # where the offered tools may run (any signed-in or anonymous caller may narrow it)
    locality = data.get('locality') or None
    if locality is not None:
        from sajha.ai.locality import LocalityError, parse as parse_locality
        try:
            parse_locality(locality if isinstance(locality, str) else '?')
        except LocalityError as e:
            return JSONResponse({'error': str(e)}, status_code=400)

    access_cache: dict = {}

    def can_use_tool(name: str) -> bool:
        if name not in access_cache:
            access_cache[name] = bool(auth.has_tool_access(name))
        return access_cache[name]

    import uuid
    ctx = RequestContext(user_id=auth.user_id or '', roles=list(auth.roles or []), is_admin=auth.is_admin,
                         trace_id=uuid.uuid4().hex, can_use_tool=can_use_tool)
    want_stream = ('text/event-stream' in request.headers.get('accept', '')
                   or request.query_params.get('stream', '').lower() in ('1', 'true', 'yes'))
    if not want_stream:
        result = await run_in_threadpool(lambda: svc.ask(question, ctx, model=model, confirm=confirm,
                                                         conversation_id=conversation_id, planner=planner,
                                                         locality=locality))
        return JSONResponse(result.to_dict())

    gen = svc.stream_ask(question, ctx, model=model, confirm=confirm, conversation_id=conversation_id,
                         planner=planner, locality=locality)
    # The shortlist (the only step that consults RBAC) runs now, while the request's DB session is open.
    first = await run_in_threadpool(next, gen)

    def events():
        yield _sse(first)
        try:
            for ev in gen:
                yield _sse(ev)
        except Exception as e:      # never leave the client without a terminal event
            logger.error(f"ask stream failed: {e}", exc_info=True)
            yield _sse({'type': 'error', 'seq': -1, 'code': 'internal_error', 'message': str(e)[:300]})
            yield _sse({'type': 'done', 'seq': -1, 'result': None})

    return StreamingResponse(events(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


# ── Conversation memory (sajha/ai/memory.py): each user sees and deletes only their own ──

def _memory_or_error():
    from sajha.ai.intelligence import get_intelligence
    svc = get_intelligence()
    if svc is None:
        return None, JSONResponse({'error': 'Intelligence service not initialized'}, status_code=503)
    return svc.memory, None


@router.get('/api/ai/conversations')
async def api_list_conversations(tool: Optional[str] = None, auth: AuthContext = Depends(require_auth)):
    """The caller's conversations, most recent first: the Ask SAJHA page's by default,
    ``?tool=<name>`` one LLM tool's, ``?tool=*`` all of them."""
    from starlette.concurrency import run_in_threadpool
    from sajha.ai.memory import ANY, conversation_view
    mem, err = _memory_or_error()
    if err:
        return err
    if not auth.user_id:
        return JSONResponse({'conversations': []})
    scope = ANY if tool == '*' else (tool or None)
    rows = await run_in_threadpool(lambda: mem.store.list(auth.user_id, tool_name=scope))
    return JSONResponse({'conversations': [conversation_view(r) for r in rows],
                         'retention_days': mem.settings.retention_days, 'enabled': mem.enabled})


@router.get('/api/ai/conversations/{conversation_id}')
async def api_get_conversation(conversation_id: str, auth: AuthContext = Depends(require_auth)):
    from starlette.concurrency import run_in_threadpool
    from sajha.ai.memory import conversation_view, turn_view
    mem, err = _memory_or_error()
    if err:
        return err
    conv = await run_in_threadpool(lambda: mem.store.get(conversation_id, auth.user_id or ''))
    if conv is None:
        return JSONResponse({'error': 'conversation not found'}, status_code=404)
    turns = await run_in_threadpool(lambda: mem.store.turns(conversation_id, auth.user_id))
    return JSONResponse({**conversation_view(conv), 'summary': conv.get('summary') or '',
                         'turns': [turn_view(t) for t in turns]})


@router.delete('/api/ai/conversations/{conversation_id}')
async def api_delete_conversation(conversation_id: str, auth: AuthContext = Depends(require_auth)):
    from starlette.concurrency import run_in_threadpool
    mem, err = _memory_or_error()
    if err:
        return err
    ok = await run_in_threadpool(lambda: mem.store.delete(conversation_id, auth.user_id or ''))
    if not ok:
        return JSONResponse({'error': 'conversation not found'}, status_code=404)
    return JSONResponse({'deleted': 1})


@router.delete('/api/ai/conversations')
async def api_delete_my_history(auth: AuthContext = Depends(require_auth)):
    """Delete every conversation of the caller (and only the caller's)."""
    from starlette.concurrency import run_in_threadpool
    mem, err = _memory_or_error()
    if err:
        return err
    if not auth.user_id:
        return JSONResponse({'deleted': 0})
    n = await run_in_threadpool(lambda: mem.store.delete_all(auth.user_id))
    return JSONResponse({'deleted': n})


@router.get('/api/ai/planners')
async def api_planners(auth: AuthContext = Depends(require_auth)):
    """Every planner (files in config/planners and Python registrations), the Ask SAJHA default
    (ai.ask.planner), the LLM-tool default (ai.planners.default) and, for admins, load problems."""
    from sajha.ai.intelligence import get_intelligence
    from sajha.ai.planners_engine import get_registry
    reg = get_registry()
    svc = get_intelligence()
    body = {'planners': reg.describe(), 'default': svc.settings.planner if svc is not None else None,
            'tool_default': reg.settings.default, 'aliases': {'model': 'react'}}
    if auth.is_admin:
        body['problems'] = reg.problems()
    return JSONResponse(body)


@router.get('/api/ai/planners/{name}')
async def api_planner(name: str, auth: AuthContext = Depends(require_auth)):
    """One planner (``name`` or ``name@version``): its stages, settings, roles and warnings."""
    from sajha.ai.planners_engine import get_registry
    try:
        pdef = get_registry().compiled(name)
    except Exception as e:
        return JSONResponse({'error': str(e)[:300]}, status_code=404)
    return JSONResponse(pdef.describe())


@router.post('/api/ai/planners/dry-run')
async def api_planner_dry_run(request: Request, auth: AuthContext = Depends(require_admin)):
    """Admins: run a planner against the mock model (ai.planners.dry_run_model) and return the stage
    path. Only read-only tools (and those named in run_tools) run; other calls return "not run".
    Body: {planner: name | name@version | inline object | overlay, question, tools?: [names],
    run_tools?: [names], input?: {...}}."""
    from starlette.concurrency import run_in_threadpool
    from sajha.ai.intelligence import get_intelligence
    from sajha.ai.llm import RequestContext
    from sajha.ai.planners_engine.dryrun import dry_run
    svc = get_intelligence()
    if svc is None:
        return JSONResponse({'error': 'Intelligence service not initialized'}, status_code=503)
    try:
        data = await request.json()
    except Exception:
        data = None
    if not isinstance(data, dict) or not str(data.get('question') or '').strip():
        return JSONResponse({'error': 'body must be {"planner": ..., "question": "..."}'}, status_code=400)
    planner = data.get('planner') or None
    if planner is not None and not isinstance(planner, (str, dict)):
        return JSONResponse({'error': 'planner must be a reference or an object'}, status_code=400)
    from sajha.ai.planners_engine import get_registry
    try:
        if isinstance(planner, dict) and 'use' not in planner:
            get_registry().inline(planner, {'name': 'dry_run__inline', 'version': '0.0.0'})
        elif planner is not None:
            get_registry().compiled(planner)
    except Exception as e:
        return JSONResponse({'error': str(e)[:1000]}, status_code=400)
    tools, run_tools = data.get('tools'), data.get('run_tools')
    for k, v in (('tools', tools), ('run_tools', run_tools)):
        if v is not None and not (isinstance(v, list) and all(isinstance(t, str) for t in v)):
            return JSONResponse({'error': f'{k} must be a list of tool names'}, status_code=400)
    ctx = RequestContext(user_id=auth.user_id or '', roles=list(auth.roles or []), is_admin=True,
                         can_use_tool=lambda n: bool(auth.has_tool_access(n)))
    try:
        out = await run_in_threadpool(lambda: dry_run(svc, planner, str(data['question'])[:8000], ctx, tools=tools,
                                                      run_tools=run_tools,
                                                      input=data.get('input') if isinstance(data.get('input'), dict) else None))
    except Exception as e:
        return JSONResponse({'error': f'{e.__class__.__name__}: {e}'[:1000]}, status_code=400)
    return JSONResponse(out)


# ── Documents (RAG, sajha/ai/rag): search, status, uploads ────────

def _doc_index_or_error():
    from sajha.ai.rag.index import get_doc_index
    idx = get_doc_index()
    if idx is None:
        return None, JSONResponse({'error': 'document search is off (ai.rag.enabled: false)'}, status_code=503)
    return idx, None


@router.post('/api/ai/docs/search')
async def api_docs_search(request: Request, auth: AuthContext = Depends(require_auth)):
    """Ask the docs: {query, top_k?, source?} -> cited passages. Callers who may not run
    sajha_search_docs search SAJHA's own guides only."""
    from starlette.concurrency import run_in_threadpool
    from sajha.ai.rag.index import SAJHA_DOCS
    idx, err = _doc_index_or_error()
    if err:
        return err
    try:
        data = await request.json()
    except Exception:
        data = None
    if not isinstance(data, dict) or not str(data.get('query') or '').strip():
        return JSONResponse({'error': 'body must be JSON: {"query": "..."}'}, status_code=400)
    query = str(data['query']).strip()[:1000]
    try:
        top_k = int(data.get('top_k') or 0) or None
    except (TypeError, ValueError):
        return JSONResponse({'error': 'top_k must be an integer'}, status_code=400)
    source = str(data.get('source') or '').strip() or None
    sources = [source] if source else None
    if not auth.has_tool_access('sajha_search_docs'):
        if source and source != SAJHA_DOCS:
            return JSONResponse({'error': 'you may search only SAJHA\'s own guides'}, status_code=403)
        sources = [SAJHA_DOCS]
    results = await run_in_threadpool(lambda: idx.search(query, top_k, sources))
    return JSONResponse({'query': query, 'results': results, 'count': len(results)})


@router.get('/api/ai/docs/status')
async def api_docs_status(auth: AuthContext = Depends(require_admin)):
    from starlette.concurrency import run_in_threadpool
    idx, err = _doc_index_or_error()
    if err:
        return err
    return JSONResponse(await run_in_threadpool(idx.stats))


@router.post('/api/ai/docs/reindex')
async def api_docs_reindex(request: Request, auth: AuthContext = Depends(require_admin)):
    """Re-sync the index now ({"force": true} re-embeds everything)."""
    from starlette.concurrency import run_in_threadpool
    idx, err = _doc_index_or_error()
    if err:
        return err
    try:
        data = await request.json()
    except Exception:
        data = {}
    force = bool((data or {}).get('force')) if isinstance(data, dict) else False
    return JSONResponse(await run_in_threadpool(lambda: idx.build(force=force)))


@router.post('/api/ai/docs/uploads')
async def api_docs_upload(request: Request, auth: AuthContext = Depends(require_admin)):
    """Add a document: JSON {filename, content} (UTF-8 text: .md, .txt, .rst, .html), or
    {filename, content_base64} for a PDF or Word (.docx) file (needs pypdf / python-docx)."""
    from starlette.concurrency import run_in_threadpool
    idx, err = _doc_index_or_error()
    if err:
        return err
    try:
        data = await request.json()
    except Exception:
        data = None
    raw = None
    if isinstance(data, dict) and isinstance(data.get('content_base64'), str):
        import base64
        import binascii
        try:
            raw = base64.b64decode(data['content_base64'], validate=True)
        except (binascii.Error, ValueError):
            return JSONResponse({'error': 'content_base64 is not valid base64'}, status_code=400)
    elif isinstance(data, dict) and isinstance(data.get('content'), str):
        raw = data['content'].encode('utf-8')
    if not isinstance(data, dict) or not data.get('filename') or raw is None:
        return JSONResponse({'error': 'body must be JSON: {"filename": "...", "content": "..."} '
                                      'or {"filename": "...", "content_base64": "..."}'}, status_code=400)
    try:
        out = await run_in_threadpool(lambda: idx.save_upload(str(data['filename']), raw))
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    return JSONResponse(out, status_code=201)


@router.delete('/api/ai/docs/uploads/{filename}')
async def api_docs_delete_upload(filename: str, auth: AuthContext = Depends(require_admin)):
    from starlette.concurrency import run_in_threadpool
    idx, err = _doc_index_or_error()
    if err:
        return err
    try:
        ok = await run_in_threadpool(lambda: idx.delete_upload(filename))
    except ValueError as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    if not ok:
        return JSONResponse({'error': 'no such upload'}, status_code=404)
    return JSONResponse({'deleted': filename})
