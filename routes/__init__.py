"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Routes Module for SAJHA MCP Server
"""

from routes.base_routes import BaseRoutes
from routes.auth_routes import AuthRoutes
from routes.dashboard_routes import DashboardRoutes
from routes.tools_routes import ToolsRoutes
from routes.admin_routes import AdminRoutes
from routes.monitoring_routes import MonitoringRoutes
from routes.api_routes import ApiRoutes
from routes.socketio_handlers import SocketIOHandlers
from routes.prompts_routes import PromptsRoutes

__all__ = [
    'BaseRoutes',
    'AuthRoutes',
    'DashboardRoutes',
    'ToolsRoutes',
    'AdminRoutes',
    'MonitoringRoutes',
    'ApiRoutes',
    'SocketIOHandlers',
    'PromptsRoutes'
]