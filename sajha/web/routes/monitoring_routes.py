"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Monitoring Routes for SAJHA MCP Server
"""

from flask import render_template
from sajha.web.routes.base_routes import BaseRoutes


class MonitoringRoutes(BaseRoutes):
    """Monitoring-related routes for system health and metrics"""

    def __init__(self, auth_manager, tools_registry):
        """Initialize monitoring routes"""
        super().__init__(auth_manager, tools_registry)

    def register_routes(self, app):
        """Register monitoring routes"""

        @app.route('/monitoring/tools')
        @self.login_required
        def monitoring_tools():
            """Tools monitoring page"""
            user_session = self.get_user_session()

            # Get tool metrics
            metrics = self.tools_registry.get_tool_metrics()

            return render_template('monitoring/monitoring_tools.html',
                                 user=user_session,
                                 metrics=metrics)

        @app.route('/monitoring/users')
        @self.admin_required
        def monitoring_users():
            """Users monitoring page"""
            user_session = self.get_user_session()

            # Get user activity (simplified for now)
            users = self.auth_manager.get_all_users()

            return render_template('monitoring/monitoring_users.html',
                                 user=user_session,
                                 users=users)