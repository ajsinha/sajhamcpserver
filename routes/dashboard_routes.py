"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Dashboard Routes for SAJHA MCP Server
"""

from flask import render_template, redirect, url_for
from routes.base_routes import BaseRoutes


class DashboardRoutes(BaseRoutes):
    """Dashboard-related routes"""

    def __init__(self, auth_manager, tools_registry):
        """Initialize dashboard routes"""
        super().__init__(auth_manager, tools_registry)

    def register_routes(self, app):
        """Register dashboard routes"""

        @app.route('/')
        def index():
            """Home page - redirect to dashboard"""
            return redirect(url_for('dashboard'))

        @app.route('/dashboard')
        @self.login_required
        def dashboard():
            """Main dashboard page"""
            user_session = self.get_user_session()

            # Get available tools
            tools = self.tools_registry.get_all_tools()

            # Filter tools based on user permissions
            if not self.auth_manager.is_admin(user_session):
                accessible_tools = self.auth_manager.get_user_accessible_tools(user_session)
                if '*' not in accessible_tools:
                    tools = [t for t in tools if t['name'] in accessible_tools]

            # Get tool errors if admin
            tool_errors = []
            if self.auth_manager.is_admin(user_session):
                tool_errors = self.tools_registry.get_tool_errors()

            return render_template('dashboard.html',
                                 user=user_session,
                                 tools=tools,
                                 tool_errors=tool_errors,
                                 is_admin=self.auth_manager.is_admin(user_session))