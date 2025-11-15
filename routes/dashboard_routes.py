"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Dashboard Routes for SAJHA MCP Server
"""

from flask import render_template, redirect, url_for
from routes.base_routes import BaseRoutes


class DashboardRoutes(BaseRoutes):
    """Dashboard-related routes"""

    def __init__(self, auth_manager, tools_registry, prompts_registry):
        """Initialize dashboard routes"""
        super().__init__(auth_manager)
        self.tools_registry = tools_registry
        self.prompts_registry = prompts_registry

    def register_routes(self, app):
        """Register dashboard routes"""

        @app.route('/')
        def index():
            """Home page - redirect to dashboard"""
            return redirect(url_for('dashboard'))

        @app.route('/dashboard')
        @self.login_required
        def dashboard():
            """Dashboard page"""
            user_session = self.get_user_session()

            # Get all tools
            user_tools = self.tools_registry.get_all_tools()

            # Tool errors - not available in this version
            tool_errors = None

            # Get prompts count
            prompts_count = 0
            if self.prompts_registry:
                try:
                    prompts = self.prompts_registry.get_all_prompts()
                    prompts_count = len(prompts) if prompts else 0
                except:
                    prompts_count = 0

            return render_template('dashboard.html',
                                   user=user_session,
                                   tools=user_tools,
                                   tool_errors=tool_errors,
                                   prompts_count=prompts_count,
                                   is_admin=self.auth_manager.is_admin(user_session))