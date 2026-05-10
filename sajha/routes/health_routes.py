"""
SAJHA MCP Server v3 — Health Check Routes
"""

from datetime import datetime
from fastapi import APIRouter
from sajha.core.config import get_settings

router = APIRouter(tags=['health'])


@router.get('/health')
async def health():
    from sajha.app import tools_registry, prompts_registry, config_reloader, VERSION
    settings = get_settings()
    return {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'version': VERSION,
        'app_name': settings.app_name,
        'tools_count': len(tools_registry.tools) if tools_registry else 0,
        'prompts_count': len(prompts_registry.prompts) if prompts_registry else 0,
        'db_type': settings.db_type,
        'hot_reload': config_reloader.get_status() if config_reloader else None,
    }
