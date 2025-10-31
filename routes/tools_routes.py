"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Tools Routes for SAJHA MCP Server
"""

from flask import render_template
from routes.base_routes import BaseRoutes


class ToolsRoutes(BaseRoutes):
    """Tools-related routes"""

    def __init__(self, auth_manager, tools_registry):
        """Initialize tools routes"""
        super().__init__(auth_manager, tools_registry)

    def register_routes(self, app):
        """Register tools routes"""

        @app.route('/tools')
        @app.route('/tools/list')
        @self.login_required
        def tools_list():
            """Tools list page"""
            user_session = self.get_user_session()

            # Get all tools
            tools = self.tools_registry.get_all_tools()

            # Filter based on user permissions
            accessible_tools = self.auth_manager.get_user_accessible_tools(user_session)
            if '*' not in accessible_tools:
                tools = [t for t in tools if t['name'] in accessible_tools]

            return render_template('tools_list.html',
                                 user=user_session,
                                 tools=tools)

        @app.route('/tools/execute/<tool_name>')
        @self.login_required
        def tool_execute(tool_name):
            """Tool execution page"""
            user_session = self.get_user_session()

            # Check if user has access to this tool
            if not self.auth_manager.has_tool_access(user_session, tool_name):
                return render_template('error.html',
                                     error="Access Denied",
                                     message=f"You don't have permission to use {tool_name}"), 403

            # Get tool details
            tool = self.tools_registry.get_tool(tool_name)
            if not tool:
                return render_template('error.html',
                                     error="Tool Not Found",
                                     message=f"Tool {tool_name} not found"), 404

            return render_template('tool_execute.html',
                                 user=user_session,
                                 tool=tool.to_mcp_format())