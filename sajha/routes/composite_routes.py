"""
SAJHA MCP Server v3 — Composite Tool Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""
import json, logging
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sajha.auth import AuthContext, require_auth, require_admin
from sajha.db.engine import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=['composite'])


@router.get('/api/composite-tools')
async def api_list(auth: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    from sajha.db.dao import CompositeToolDAO
    dao = CompositeToolDAO(db)
    return JSONResponse({'tools': [dao.to_dict(r) for r in dao.get_all(enabled_only=False)]})


@router.get('/api/composite-tools/{name}')
async def api_get(name: str, auth: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    from sajha.db.dao import CompositeToolDAO
    dao = CompositeToolDAO(db)
    rec = dao.get_by_name(name)
    if not rec:
        return JSONResponse({'error': 'Not found'}, status_code=404)
    # Include live schemas from the registered tool
    result = dao.to_dict(rec)
    try:
        from sajha.tools.composite_tool import CompositeToolEngine
        engine = _get_engine()
        if engine:
            defn = engine.get_definition(name)
            if defn:
                from sajha.tools.tools_registry import ToolsRegistry
                reg = ToolsRegistry.get_instance()
                tool = reg.get_tool(name)
                if tool:
                    result['input_schema'] = tool.get_input_schema()
                    result['output_schema'] = tool.get_output_schema()
    except: pass
    return JSONResponse(result)


@router.post('/api/composite-tools')
async def api_create(request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    from sajha.db.dao import CompositeToolDAO
    data = await request.json()
    dao = CompositeToolDAO(db)
    if dao.get_by_name(data.get('name', '')):
        return JSONResponse({'error': 'Name already exists'}, status_code=409)
    rec = dao.create(
        name=data['name'], master_tool=data['master_tool'],
        arrangement=data.get('arrangement', 'sibling'),
        description=data.get('description', ''),
        master_output_key=data.get('master_output_key', 'master'),
        record_path=data.get('record_path', ''),
        created_by=auth.user_id,
        steps=data.get('steps', []),
    )
    # Build and register the tool immediately
    _rebuild_composite(db, rec.name)
    return JSONResponse({'success': True, 'name': rec.name})


@router.put('/api/composite-tools/{name}')
async def api_update(name: str, request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    from sajha.db.dao import CompositeToolDAO
    data = await request.json()
    dao = CompositeToolDAO(db)
    rec = dao.update(name, **data)
    if not rec:
        return JSONResponse({'error': 'Not found'}, status_code=404)
    _rebuild_composite(db, name)
    return JSONResponse({'success': True})


@router.delete('/api/composite-tools/{name}')
async def api_delete(name: str, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    from sajha.db.dao import CompositeToolDAO
    if CompositeToolDAO(db).delete(name):
        try:
            from sajha.tools.tools_registry import ToolsRegistry
            ToolsRegistry.get_instance().unregister_tool(name)
        except: pass
        return JSONResponse({'success': True})
    return JSONResponse({'error': 'Not found'}, status_code=404)


@router.get('/api/composite-tools/{name}/preview-schema')
async def api_preview_schema(name: str, auth: AuthContext = Depends(require_auth), db: Session = Depends(get_db)):
    """Preview the auto-generated input/output schemas without registering."""
    from sajha.db.dao import CompositeToolDAO
    from sajha.tools.tools_registry import ToolsRegistry
    from sajha.tools.composite_tool import CompositeTool
    dao = CompositeToolDAO(db)
    rec = dao.get_by_name(name)
    if not rec:
        return JSONResponse({'error': 'Not found'}, status_code=404)
    defn = dao.to_dict(rec)
    registry = ToolsRegistry.get_instance()
    try:
        tool = CompositeTool(defn, registry)
        return JSONResponse({
            'input_schema': tool.get_input_schema(),
            'output_schema': tool.get_output_schema(),
        })
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)


def _get_engine():
    try:
        from sajha.tools.composite_tool import _engine
        return _engine
    except: return None


def _rebuild_composite(db, name: str):
    """Rebuild a single composite tool after create/update."""
    try:
        from sajha.tools.tools_registry import ToolsRegistry
        from sajha.tools.composite_tool import CompositeToolEngine
        registry = ToolsRegistry.get_instance()
        engine = CompositeToolEngine(registry)
        engine.load_from_db(db)
    except Exception as e:
        logger.warning(f"Failed to rebuild composite {name}: {e}")


# ── Web UI Page ──────────────────────────────────────────────
from sajha.app import render

@router.get('/composite/builder')
async def composite_builder_page(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.tools.tools_registry import ToolsRegistry
    reg = ToolsRegistry.get_instance()
    tool_names = sorted(reg.tools.keys()) if reg else []
    return render(request, 'composite/builder.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'is_admin': auth.is_admin,
        'tool_names': tool_names,
    })
