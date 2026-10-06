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
        'state': _state_info(),
        'sandbox': _sandbox_info(),
    }


def _sandbox_info():
    """Sandbox backend for user-code tools (no probe here; /api/sandbox/status probes)."""
    try:
        from sajha.sandbox import get_backend, load_settings
        s = load_settings()
        return {'backend': get_backend(None, s).name, 'default_backend': s.default_backend,
                'enforce_for_generated_tools': s.enforce_for_generated_tools}
    except Exception as e:
        return {'backend': 'unavailable', 'error': str(e)}


def _state_info():
    """state.backend in use (memory | redis | database), whether it answers, and this worker's id."""
    try:
        from sajha.core.state import health_info
        return health_info()
    except Exception as e:
        return {'backend': 'unavailable', 'error': str(e)}
