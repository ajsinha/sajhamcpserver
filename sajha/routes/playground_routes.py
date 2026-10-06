"""
SAJHA MCP Server — Python Playground routes

/playground                 the page (signed-in users): a small notebook running Python in
                            the browser with Pyodide (WebAssembly) in a Web Worker
/api/playground/worker.js   the worker script, with the only CSP that allows WebAssembly
/api/playground/sajha.py    the source of the ``sajha`` module installed into Pyodide
/api/playground/runtime.py  the source of the cell runner installed into Pyodide
/api/playground/tools       the tools the signed-in user may call (sajha.tools())

(The worker and the two Python files are code the page loads, not pages, so they live under
/api/: an expired session gets a JSON 401 rather than a redirect to the landing page.)

No route here runs user code: Python runs in the visitor's browser. Tool calls from the
playground go through the ordinary POST /api/tools/execute with the user's session, so
access control, usage logging and API limits are the same as on the Tools page.
Settings and headers: sajha/web/playground.py.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from sajha.auth import AuthContext, require_auth
from sajha.web import playground as pg

logger = logging.getLogger(__name__)
router = APIRouter(tags=['playground'])


def _disabled(request: Request):
    from sajha.app import render
    return render(request, 'common/error.html', {
        'error': 'Python Playground is switched off',
        'message': 'An administrator has set playground.enabled to false on this server.',
    }, status_code=404)


@router.get('/playground')
async def playground_page(request: Request, auth: AuthContext = Depends(require_auth)):
    """The Python Playground: Python in the browser (Pyodide), with the sajha bridge module."""
    from sajha.app import render
    s = pg.load_settings()
    for e in s.errors:
        logger.warning(f'playground config: {e}')
    if not s.enabled:
        return _disabled(request)
    assets = pg.asset_status(s)
    resp = render(request, 'playground/playground.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'pg_settings': s,
        'pg_assets': assets,
        'pg_data': {
            'indexURL': s.index_url,
            'version': s.pyodide_version,
            'assets': s.assets,
            'assetsOk': assets['ok'],
            'vendoredPackages': assets['packages'],
            'examples': pg.EXAMPLES,
            'user': auth.user_id or '',
        },
    })
    resp.headers.update(pg.page_headers(s))
    return resp


@router.get('/api/playground/worker.js')
async def playground_worker(auth: AuthContext = Depends(require_auth)):
    s = pg.load_settings()
    if not s.enabled:
        return Response('// playground disabled\n', status_code=404, media_type='text/javascript')
    return Response(pg.worker_source(), media_type='text/javascript', headers=pg.worker_headers(s))


@router.get('/api/playground/sajha.py')
async def playground_bridge(auth: AuthContext = Depends(require_auth)):
    """The sajha module's source, installed into Pyodide as sajha/__init__.py."""
    return Response(pg.bridge_source(), media_type='text/x-python; charset=utf-8',
                    headers={**pg.isolation_headers(), 'Cache-Control': 'no-cache'})


@router.get('/api/playground/runtime.py')
async def playground_runtime(auth: AuthContext = Depends(require_auth)):
    return Response(pg.runtime_source(), media_type='text/x-python; charset=utf-8',
                    headers={**pg.isolation_headers(), 'Cache-Control': 'no-cache'})


@router.get('/api/playground/tools')
async def api_playground_tools(auth: AuthContext = Depends(require_auth)):
    """The enabled tools this caller may execute: what sajha.tools() returns."""
    from sajha.app import tools_registry
    out = []
    for name, tool in sorted(dict(getattr(tools_registry, 'tools', None) or {}).items()):
        if getattr(tool, 'enabled', True) is False:
            continue
        try:
            if not auth.has_tool_access(name):
                continue
        except Exception:
            continue
        desc = str(getattr(tool, 'description', '') or '').strip()
        meta = getattr(tool, '_metadata', None) or {}
        out.append({'name': name, 'description': desc.split('\n')[0][:300],
                    'category': (meta.get('category') if isinstance(meta, dict) else '') or ''})
    return JSONResponse({'tools': out, 'count': len(out)})
