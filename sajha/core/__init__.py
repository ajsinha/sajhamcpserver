"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Core module for SAJHA MCP Server

The names below load on first use (PEP 562), so importing a submodule such as
``sajha.core.mcp_mrtr`` does not pull in the MCP handler and everything it imports (that
eager import made ``sajha.accounts.errors`` circular when it was imported first).
"""

from importlib import import_module

_LAZY = {
    'PropertiesConfigurator': '.properties_configurator',
    'MCPHandler': '.mcp_handler',
    'PromptsRegistry': '.prompts_registry',
    'get_prompts_registry': '.prompts_registry',
    'HotReloadManager': '.hot_reload_manager',
    'ConfigReloader': '.hot_reload_manager',
    'get_config_reloader': '.hot_reload_manager',
}

__all__ = list(_LAZY)


def __getattr__(name):
    if name in _LAZY:
        value = getattr(import_module(_LAZY[name], __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
