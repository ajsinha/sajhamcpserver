"""
SAJHA MCP Server - Main Package

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

This package contains all core modules for the SAJHA MCP Server:
- core: Authentication, MCP handling, prompts, configuration
- tools: Tool registry and implementations
- web: Flask web application and routes
- apiclient: External API clients
- ir: Investor relations scrapers
"""

__version__ = '2.9.8'
__author__ = 'Ashutosh Sinha'
__email__ = 'ajsinha@gmail.com'

# The names below are loaded on first use (PEP 562), so importing a light subpackage such as the
# SAJHA Net protocol core (``sajha.net``) does not load the whole server: the SAJHA Net agent builds on
# that core without the app (tests/test_sajhanet_agent_boundary.py).
_LAZY = {
    'AuthManager': 'sajha.auth',             # sign-in, JWTs and API keys (sajha/auth/__init__.py)
    'MCPHandler': 'sajha.core',
    'PromptsRegistry': 'sajha.core',
    'PropertiesConfigurator': 'sajha.core',
    'HotReloadManager': 'sajha.core',
    'ConfigReloader': 'sajha.core',
    'get_config_reloader': 'sajha.core',
    'BaseMCPTool': 'sajha.tools',
    'ToolsRegistry': 'sajha.tools',
}


def __getattr__(name):
    mod = _LAZY.get(name)
    if mod is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    import importlib
    value = getattr(importlib.import_module(mod), name)
    globals()[name] = value
    return value


__all__ = [
    'AuthManager',
    'MCPHandler', 
    'PromptsRegistry',
    'PropertiesConfigurator',
    'HotReloadManager',
    'ConfigReloader',
    'get_config_reloader',
    'BaseMCPTool',
    'ToolsRegistry',
    '__version__',
    '__author__',
    '__email__'
]
