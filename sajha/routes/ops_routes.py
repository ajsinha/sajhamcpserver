"""
SAJHA MCP Server v4.0.0 — Operations, Tenancy, Versioning & Plugins Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""
import json, logging
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sajha.auth import AuthContext, require_auth, require_admin

logger = logging.getLogger(__name__)
router = APIRouter(tags=['ops'])

# ── Health Probes ─────────────────────────────────────────────

@router.get('/health')
async def health_liveness():
    from sajha.observability import get_health
    h = get_health()
    return JSONResponse(h.liveness() if h else {'status': 'ok'})

@router.get('/ready')
async def health_readiness():
    from sajha.observability import get_health
    h = get_health()
    return JSONResponse(h.readiness() if h else {'status': 'ok'})

# ── Metrics ───────────────────────────────────────────────────

@router.get('/api/metrics')
async def api_metrics(auth: AuthContext = Depends(require_auth)):
    from sajha.observability import get_collector
    c = get_collector()
    if not c: return JSONResponse({'error': 'Metrics not initialized'})
    return JSONResponse(c.get_summary())

@router.get('/api/metrics/tools')
async def api_metrics_tools(auth: AuthContext = Depends(require_auth)):
    from sajha.observability import get_collector
    c = get_collector()
    if not c: return JSONResponse({'tools': []})
    return JSONResponse({'tools': c.get_all_metrics()})

@router.get('/api/metrics/tools/{tool_name}')
async def api_metrics_tool(tool_name: str, auth: AuthContext = Depends(require_auth)):
    from sajha.observability import get_collector
    c = get_collector()
    if not c: return JSONResponse({'error': 'Not found'}, 404)
    m = c.get_tool_metrics(tool_name)
    return JSONResponse(m if m else {'error': 'No metrics for tool'})

# ── Tool Versioning ───────────────────────────────────────────

@router.get('/api/tool-versions')
async def api_list_versions(auth: AuthContext = Depends(require_auth)):
    from sajha.core.tool_versioning import ToolVersionManager
    # For now return from in-memory; later from DB
    return JSONResponse({'versions': []})

@router.post('/api/tool-versions/{tool_name}/deprecate')
async def api_deprecate_tool(tool_name: str, request: Request, auth: AuthContext = Depends(require_admin)):
    data = await request.json()
    from sajha.core.tool_versioning import ToolVersionManager
    return JSONResponse({'success': True, 'tool_name': tool_name})

# ── Contract Testing ──────────────────────────────────────────

@router.post('/api/contract-test/{tool_name}')
async def api_test_tool(tool_name: str, request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.core.tool_versioning import ContractTestRunner
    from sajha.app import tools_registry
    runner = ContractTestRunner(tools_registry)
    data = await request.json() if request.headers.get('content-length', '0') != '0' else {}
    result = runner.test_tool(tool_name, data.get('arguments'))
    return JSONResponse(result.to_dict())

@router.post('/api/contract-test')
async def api_test_all(auth: AuthContext = Depends(require_admin)):
    from sajha.core.tool_versioning import ContractTestRunner
    from sajha.app import tools_registry
    runner = ContractTestRunner(tools_registry)
    results = runner.test_all()
    passed = sum(1 for r in results if r.passed)
    return JSONResponse({
        'total': len(results), 'passed': passed, 'failed': len(results) - passed,
        'results': [r.to_dict() for r in results],
    })

# ── Multi-Tenancy ─────────────────────────────────────────────

@router.get('/api/tenants')
async def api_list_tenants(auth: AuthContext = Depends(require_admin)):
    from sajha.core.tenancy import get_tenant_manager
    tm = get_tenant_manager()
    return JSONResponse({'tenants': tm.list_tenants() if tm else []})

@router.post('/api/tenants')
async def api_create_tenant(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.core.tenancy import get_tenant_manager
    data = await request.json()
    tm = get_tenant_manager()
    if not tm: return JSONResponse({'error': 'Tenancy not initialized'}, 503)
    try:
        t = tm.create_tenant(data['id'], data['name'],
            tool_patterns=data.get('tool_patterns', ['*']),
            blocked_tools=data.get('blocked_tools', []))
        if 'quota' in data:
            from sajha.core.tenancy import TenantQuota
            t.quota = TenantQuota(**data['quota'])
        return JSONResponse({'success': True, 'tenant': t.to_dict()})
    except ValueError as e:
        return JSONResponse({'error': str(e)}, 409)

@router.get('/api/tenants/{tenant_id}')
async def api_get_tenant(tenant_id: str, auth: AuthContext = Depends(require_admin)):
    from sajha.core.tenancy import get_tenant_manager
    tm = get_tenant_manager()
    t = tm.get_tenant(tenant_id) if tm else None
    if not t: return JSONResponse({'error': 'Not found'}, 404)
    return JSONResponse(t.to_dict())

@router.put('/api/tenants/{tenant_id}')
async def api_update_tenant(tenant_id: str, request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.core.tenancy import get_tenant_manager
    data = await request.json()
    tm = get_tenant_manager()
    t = tm.update_tenant(tenant_id, **data) if tm else None
    if not t: return JSONResponse({'error': 'Not found'}, 404)
    return JSONResponse({'success': True})

@router.delete('/api/tenants/{tenant_id}')
async def api_delete_tenant(tenant_id: str, auth: AuthContext = Depends(require_admin)):
    from sajha.core.tenancy import get_tenant_manager
    tm = get_tenant_manager()
    if tm and tm.delete_tenant(tenant_id):
        return JSONResponse({'success': True})
    return JSONResponse({'error': 'Not found or cannot delete default'}, 404)

# ── Plugins ───────────────────────────────────────────────────

@router.get('/api/plugins')
async def api_list_plugins(auth: AuthContext = Depends(require_admin)):
    from sajha.core.plugins import get_plugin_manager
    pm = get_plugin_manager()
    if not pm: return JSONResponse({'plugins': []})
    return JSONResponse({
        'plugins': pm.list_plugins(),
        'status': pm.get_status(),
    })

@router.post('/api/plugins/{name}/load')
async def api_load_plugin(name: str, auth: AuthContext = Depends(require_admin)):
    from sajha.core.plugins import get_plugin_manager
    pm = get_plugin_manager()
    if not pm: return JSONResponse({'error': 'Plugin manager not initialized'}, 503)
    status = pm.load_plugin(name)
    return JSONResponse(status.to_dict())

@router.post('/api/plugins/{name}/unload')
async def api_unload_plugin(name: str, auth: AuthContext = Depends(require_admin)):
    from sajha.core.plugins import get_plugin_manager
    pm = get_plugin_manager()
    if pm and pm.unload_plugin(name):
        return JSONResponse({'success': True})
    return JSONResponse({'error': 'Not found'}, 404)

@router.post('/api/plugins/discover')
async def api_discover_plugins(auth: AuthContext = Depends(require_admin)):
    from sajha.core.plugins import get_plugin_manager
    pm = get_plugin_manager()
    if not pm: return JSONResponse({'plugins': []})
    manifests = pm.discover()
    return JSONResponse({'plugins': [m.to_dict() for m in manifests]})
