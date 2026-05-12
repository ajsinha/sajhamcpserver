"""
SAJHA MCP Server v3 — AI Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Admin UI + API for LLM provider management, model selection,
user preferences, token usage, and semantic tool resolution.
"""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse

from sajha.auth import AuthContext, require_auth, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(tags=['ai'])


def _get_gateway():
    from sajha.ai.gateway import get_gateway
    return get_gateway()


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
        if gw:
            prov_inst = gw.get_provider(p.provider_type)
            if prov_inst:
                try: healthy = prov_inst.health_check()
                except Exception as e:
                    logger.warning(f"Error handled: {e}", exc_info=True)
                    pass

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
    prov = gw.get_provider(provider_type)
    if not prov:
        return JSONResponse({'error': f'Provider {provider_type} not registered'}, status_code=404)
    healthy = prov.health_check()
    return JSONResponse({'provider': provider_type, 'healthy': healthy})


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

    # Also update the in-memory gateway
    gw = _get_gateway()
    if gw:
        if 'provider' in data: gw.config.default_provider = data['provider']
        if 'model' in data: gw.config.default_model = data['model']

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
    return JSONResponse({'usage': gw.get_token_usage(), 'cache': gw._cache.stats()})


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

    try:
        resp = gw.complete(
            prompt=prompt,
            user_id=auth.user_id,
            provider=data.get('provider', ''),
            model=data.get('model', ''),
            system=data.get('system', ''),
            temperature=float(data.get('temperature', 0)),
            max_tokens=int(data.get('max_tokens', 0)),
        )
        return JSONResponse({
            'content': resp.content,
            'model': resp.model,
            'provider': resp.provider,
            'tokens': {'input': resp.input_tokens, 'output': resp.output_tokens, 'total': resp.total_tokens},
            'cost_usd': round(resp.cost_usd, 6),
            'latency_ms': resp.latency_ms,
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


# ── Provider Registry Info ────────────────────────────────────

@router.get('/api/ai/registry')
async def api_registry(auth: AuthContext = Depends(require_admin)):
    """List all registered provider classes (available to configure)."""
    from sajha.ai.providers import get_registered_types
    return JSONResponse({
        'registered_types': get_registered_types(),
        'info': 'Use register_provider_class() to add custom local providers',
    })
