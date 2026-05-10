"""
SAJHA MCP Server v3 — API Key Management Routes
Copyright All rights Reserved 2025-2030, Ashutosh Sinha
"""

import json
import secrets
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from sajha.db.engine import get_db
from sajha.db.models import ApiKey
from sajha.db.dao import ApiKeyDAO, AuditDAO
from sajha.auth import require_admin, AuthContext
from sajha.app import render

router = APIRouter(prefix='/admin/apikeys', tags=['apikeys'])


@router.get('')
@router.get('/')
async def apikeys_list(request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    dao = ApiKeyDAO(db)
    keys = dao.get_all_keys(include_disabled=True)
    keys_data = []
    total_requests = 0
    enabled = 0
    for k in keys:
        total_requests += k.usage_count
        if k.enabled:
            enabled += 1
        keys_data.append({
            'id': k.id,
            'key': k.key_prefix + '...',  # Template uses key.key for display
            'key_prefix': k.key_prefix,
            'name': k.name,
            'description': k.description or '',
            'enabled': k.enabled,
            'created_at': k.created_at.isoformat() + 'Z' if k.created_at else '',
            'last_used': k.last_used.isoformat() + 'Z' if k.last_used else None,
            'usage_count': k.usage_count,
            'tool_access_mode': k.tool_access_mode,
            'tool_access': {'mode': k.tool_access_mode},
            'usage_stats': {'total_requests': k.usage_count},
        })
    return render(request, 'admin/apikeys_list.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'apikeys': keys_data,
        'stats': {
            'total_keys': len(keys_data),
            'enabled_keys': enabled,
            'disabled_keys': len(keys_data) - enabled,
            'total_requests': total_requests,
        },
        'is_admin': True,
    })


@router.get('/create')
async def apikey_create_page(request: Request, auth: AuthContext = Depends(require_admin)):
    from sajha.app import tools_registry
    tools = list(tools_registry.tools.keys()) if tools_registry else []
    return render(request, 'admin/apikeys_create.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'available_tools': tools,
        'is_admin': True,
    })


@router.post('/create')
async def apikey_create(request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    data = await request.json()
    name = data.get('name', 'Unnamed Key')
    description = data.get('description', '')
    mode = data.get('tool_access_mode', 'all')
    tool_list = data.get('tool_list', [])

    # Generate key
    raw_key = f'sja_{secrets.token_hex(24)}'
    dao = ApiKeyDAO(db)

    api_key = ApiKey(
        key_hash=dao.hash_key(raw_key),
        key_prefix=raw_key[:8],
        name=name,
        description=description,
        tool_access_mode=mode,
        tool_access_list=json.dumps(tool_list) if tool_list else None,
    )
    dao.create(api_key)

    AuditDAO(db).log('apikey.create', auth.user_id, 'apikey', name)
    return JSONResponse({'success': True, 'key': raw_key, 'name': name})


@router.get('/{key_id}/view')
async def apikey_view(key_id: str, request: Request, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    dao = ApiKeyDAO(db)
    key = dao.get_by_id(key_id)
    if not key:
        return render(request, 'common/error.html', {'error': 'Not Found', 'message': 'API key not found'}, status_code=404)

    return render(request, 'admin/apikeys_view.html', {
        'user': {'user_id': auth.user_id, 'user_name': auth.user_name, 'roles': auth.roles},
        'apikey': {
            'id': key.id, 'key_prefix': key.key_prefix, 'name': key.name,
            'description': key.description, 'enabled': key.enabled,
            'created_at': key.created_at.isoformat() if key.created_at else '',
            'last_used': key.last_used.isoformat() if key.last_used else None,
            'usage_count': key.usage_count, 'tool_access_mode': key.tool_access_mode,
            'tool_access_list': json.loads(key.tool_access_list or '[]'),
        },
        'is_admin': True,
    })


@router.post('/{key_id}/toggle')
async def apikey_toggle(key_id: str, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    dao = ApiKeyDAO(db)
    key = dao.get_by_id(key_id)
    if not key:
        return JSONResponse({'error': 'Not found'}, status_code=404)
    key.enabled = not key.enabled
    dao.update(key)
    AuditDAO(db).log('apikey.toggle', auth.user_id, 'apikey', key.name, {'enabled': key.enabled})
    return JSONResponse({'success': True, 'enabled': key.enabled})


@router.delete('/{key_id}/delete')
async def apikey_delete(key_id: str, auth: AuthContext = Depends(require_admin), db: Session = Depends(get_db)):
    dao = ApiKeyDAO(db)
    key = dao.get_by_id(key_id)
    if not key:
        return JSONResponse({'error': 'Not found'}, status_code=404)
    name = key.name
    dao.delete(key)
    AuditDAO(db).log('apikey.delete', auth.user_id, 'apikey', name)
    return JSONResponse({'success': True})
