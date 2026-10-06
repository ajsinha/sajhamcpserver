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

from sajha.auth import AuthManager   # sign-in, JWTs and API keys (sajha/auth/__init__.py)
from sajha.core import (
    MCPHandler,
    PromptsRegistry,
    PropertiesConfigurator,
    HotReloadManager,
    ConfigReloader,
    get_config_reloader
)

from sajha.tools import (
    BaseMCPTool,
    ToolsRegistry
)

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
