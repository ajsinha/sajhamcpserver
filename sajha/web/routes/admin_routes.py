"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Admin Routes for SAJHA MCP Server
"""

from flask import render_template
from sajha.web.routes.base_routes import BaseRoutes


class AdminRoutes(BaseRoutes):
    """Admin-related routes for managing tools and users"""

    def __init__(self, auth_manager, tools_registry):
        """Initialize admin routes"""
        super().__init__(auth_manager, tools_registry)

    def register_routes(self, app):
        """Register admin routes"""

        @app.route('/admin/tools')
        @self.admin_required
        def admin_tools():
            """Admin tools management page"""
            user_session = self.get_user_session()

            # Get all tools with metrics
            tools_metrics = self.tools_registry.get_tool_metrics()
            tool_errors = self.tools_registry.get_tool_errors()

            return render_template('admin/admin_tools.html',
                                 user=user_session,
                                 tools_metrics=tools_metrics,
                                 tool_errors=tool_errors)

        @app.route('/admin/tools/<tool_name>/config')
        @self.admin_required
        def tool_config_page(tool_name):
            """Tool configuration editor page"""
            user_session = self.get_user_session()

            # Verify tool exists
            tool = self.tools_registry.get_tool(tool_name)
            if not tool and tool_name not in self.tools_registry.tool_configs:
                return render_template('common/error.html',
                                     user=user_session,
                                     error="Tool Not Found",
                                     message=f"Tool '{tool_name}' does not exist"), 404

            return render_template('tools/tool_config.html',
                                 user=user_session,
                                 tool_name=tool_name)

        @app.route('/admin/users')
        @self.admin_required
        def admin_users():
            """Admin users management page"""
            user_session = self.get_user_session()

            # Get all users
            users = self.auth_manager.get_all_users()

            return render_template('admin/admin_users.html',
                                 user=user_session,
                                 users=users)

        @app.route('/admin/users/create')
        @self.admin_required
        def admin_user_create():
            """Create new user page"""
            user_session = self.get_user_session()

            # Get all users for validation
            users = self.auth_manager.get_all_users()

            return render_template('admin/admin_user_create.html',
                                 user=user_session,
                                 users=users)

        @app.route('/admin/users/<user_id>/config')
        @self.admin_required
        def user_config_page(user_id):
            """User configuration editor page"""
            user_session = self.get_user_session()

            # Verify user exists
            user_data = self.auth_manager.get_user(user_id)
            if not user_data:
                return render_template('common/error.html',
                                     user=user_session,
                                     error="User Not Found",
                                     message=f"User '{user_id}' does not exist"), 404

            return render_template('common/user_config.html',
                                 user=user_session,
                                 user_id=user_id)