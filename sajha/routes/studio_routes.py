"""
SAJHA MCP Server v3 — Studio Routes (Tool Development)
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

from fastapi import APIRouter, Request, Depends
from sajha.auth import require_auth, AuthContext
from sajha.app import render

router = APIRouter(prefix='/studio', tags=['studio'])


def _studio_ctx(auth: AuthContext) -> dict:
    from sajha.app import tools_registry
    return {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'sample_code': '',
        'existing_tools': list(tools_registry.tools.keys()) if tools_registry else [],
        'examples': [],  # Studio example configs
    }


@router.get('')
@router.get('/')
async def studio_home(request: Request, auth: AuthContext = Depends(require_auth)):
    return render(request, 'admin/studio/studio_home.html', _studio_ctx(auth))


@router.get('/rest')
async def studio_rest(request: Request, auth: AuthContext = Depends(require_auth)):
    return render(request, 'admin/studio/studio_rest.html', _studio_ctx(auth))


@router.get('/dbquery')
async def studio_dbquery(request: Request, auth: AuthContext = Depends(require_auth)):
    return render(request, 'admin/studio/studio_dbquery.html', _studio_ctx(auth))


@router.get('/script')
async def studio_script(request: Request, auth: AuthContext = Depends(require_auth)):
    return render(request, 'admin/studio/studio_script.html', _studio_ctx(auth))


@router.get('/livelink')
async def studio_livelink(request: Request, auth: AuthContext = Depends(require_auth)):
    return render(request, 'admin/studio/studio_livelink.html', _studio_ctx(auth))


@router.get('/olap')
async def studio_olap(request: Request, auth: AuthContext = Depends(require_auth)):
    return render(request, 'admin/studio/studio_olap.html', _studio_ctx(auth))


@router.get('/powerbi')
async def studio_powerbi(request: Request, auth: AuthContext = Depends(require_auth)):
    return render(request, 'admin/studio/studio_powerbi.html', _studio_ctx(auth))


@router.get('/powerbidax')
async def studio_powerbidax(request: Request, auth: AuthContext = Depends(require_auth)):
    return render(request, 'admin/studio/studio_powerbidax.html', _studio_ctx(auth))


@router.get('/sharepoint')
async def studio_sharepoint(request: Request, auth: AuthContext = Depends(require_auth)):
    return render(request, 'admin/studio/studio_sharepoint.html', _studio_ctx(auth))


@router.get('/examples')
async def studio_examples(request: Request, auth: AuthContext = Depends(require_auth)):
    return render(request, 'admin/studio/studio_examples.html', _studio_ctx(auth))
