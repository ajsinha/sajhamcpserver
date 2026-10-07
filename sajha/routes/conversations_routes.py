"""
SAJHA MCP Server — the Conversations page: a user's own conversation memory.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

  GET /conversations                 the page: the caller's own conversations (Ask SAJHA and each
                                     LLM tool), open one, continue it in Ask, delete one or all
  GET /api/ai/conversation-counts    admins: how many conversations are stored per scope (counts
                                     only; nobody reads another user's conversations)

The page reads and deletes through the conversation endpoints in sajha/routes/ai_routes.py
(``GET /api/ai/conversations?tool=…``, ``GET/DELETE /api/ai/conversations/{id}``,
``DELETE /api/ai/conversations``). Design: docs/architecture/LLM Tools.md §10.6.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from sajha.app import render
from sajha.auth import AuthContext, require_admin, require_auth

logger = logging.getLogger(__name__)

router = APIRouter(tags=['ai'])


def _memory():
    try:
        from sajha.ai.intelligence import get_intelligence
        svc = get_intelligence()
    except Exception:
        svc = None
    return getattr(svc, 'memory', None) if svc is not None else None


def _llm_tools_with_memory() -> list:
    """LLM tools that keep conversations (llm.memory.mode conversation): the page's scope filter."""
    try:
        from sajha.app import tools_registry
        cfgs = getattr(tools_registry, 'tool_configs', {}) or {}
    except Exception:
        cfgs = {}
    out = []
    for name, cfg in sorted(cfgs.items()):
        llm = cfg.get('llm') if isinstance(cfg, dict) else None
        if isinstance(llm, dict) and ((llm.get('memory') or {}).get('mode') == 'conversation'):
            out.append(name)
    return out


@router.get('/conversations')
async def conversations_page(request: Request, auth: AuthContext = Depends(require_auth)):
    mem = _memory()
    return render(request, 'ai/conversations.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'conv_data': {
            'tools': _llm_tools_with_memory(),
            'enabled': bool(mem is not None and getattr(mem, 'enabled', False)),
            'available': mem is not None,
            'is_admin': bool(auth.is_admin),
            'signed_in_user': bool(auth.user_id),
        },
    })


@router.get('/api/ai/conversation-counts')
async def conversation_counts(auth: AuthContext = Depends(require_admin)):
    """Stored conversations per scope (``ask`` is the Ask SAJHA page). Counts only."""
    mem = _memory()
    if mem is None:
        return JSONResponse({'error': 'Intelligence service not initialized'}, status_code=503)
    try:
        counts = await run_in_threadpool(mem.store.counts)
    except Exception as e:
        logger.warning(f'conversation counts: {e}')
        return JSONResponse({'error': f'conversation memory unavailable: {e}'[:300]}, status_code=503)
    return JSONResponse({'counts': counts, 'total': sum(counts.values()),
                         'retention_days': getattr(getattr(mem, 'settings', None), 'retention_days', None)})
