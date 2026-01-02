"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Routes Module for SAJHA MCP Server v2.1.0
"""

from .base_routes import BaseRoutes
from .auth_routes import AuthRoutes
from .dashboard_routes import DashboardRoutes
from .tools_routes import ToolsRoutes
from .admin_routes import AdminRoutes
from .monitoring_routes import MonitoringRoutes
from .api_routes import ApiRoutes
from .socketio_handlers import SocketIOHandlers
from .prompts_routes import PromptsRoutes
from .help_routes import HelpRoutes
from .docs_routes import DocsRoutes
from .apikeys_routes import APIKeysRoutes

__all__ = [
    'BaseRoutes',
    'AuthRoutes',
    'DashboardRoutes',
    'ToolsRoutes',
    'AdminRoutes',
    'MonitoringRoutes',
    'ApiRoutes',
    'SocketIOHandlers',
    'PromptsRoutes',
    'HelpRoutes',
    'DocsRoutes',
    'APIKeysRoutes'
]