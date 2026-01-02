"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
Help Routes for SAJHA MCP Server
"""

from flask import render_template, jsonify
from sajha.web.routes.base_routes import BaseRoutes
from sajha.core.tool_groups_manager import get_tool_groups_manager


class HelpRoutes(BaseRoutes):
    """Help and About page routes - accessible without authentication"""

    def __init__(self, auth_manager):
        """Initialize help routes"""
        super().__init__(auth_manager)
        # Initialize tool groups manager (will start background refresh)
        self.tool_groups_manager = get_tool_groups_manager()

    def _get_current_user(self):
        """Get current user if logged in"""
        user = None
        try:
            from flask import session
            if 'token' in session:
                user = self.auth_manager.validate_session(session['token'])
        except:
            pass
        return user

    def register_routes(self, app):
        """Register help routes"""

        @app.route('/help')
        def help_page():
            """Help page - accessible without login"""
            user = self._get_current_user()
            
            # Get dynamic tool groups
            tool_groups = self.tool_groups_manager.get_groups()
            tool_stats = self.tool_groups_manager.get_stats()
            
            return render_template('help/help.html', 
                                 user=user, 
                                 tool_groups=tool_groups,
                                 tool_stats=tool_stats)

        @app.route('/about')
        def about_page():
            """About page - accessible without login"""
            user = self._get_current_user()
            
            # Get tool stats for about page
            tool_stats = self.tool_groups_manager.get_stats()
            
            return render_template('help/about.html', user=user, tool_stats=tool_stats)

        @app.route('/api/tool-groups')
        def api_tool_groups():
            """API endpoint to get tool groups (for dynamic updates)"""
            return jsonify(self.tool_groups_manager.to_dict())

        @app.route('/api/tool-groups/refresh', methods=['POST'])
        def api_tool_groups_refresh():
            """API endpoint to force refresh tool groups"""
            self.tool_groups_manager.refresh()
            return jsonify({
                'success': True,
                'message': 'Tool groups refreshed',
                'stats': self.tool_groups_manager.get_stats()
            })

        @app.route('/api/tool-groups/<group_name>')
        def api_tool_group_detail(group_name):
            """API endpoint to get tools in a specific group"""
            group = self.tool_groups_manager.get_group(group_name)
            if not group:
                return jsonify({'error': 'Group not found'}), 404
            
            tools = self.tool_groups_manager.get_tools_in_group(group_name)
            return jsonify({
                'group': group,
                'tools': tools
            })

        @app.route('/api/tool-groups/search')
        def api_tool_search():
            """API endpoint to search tools"""
            from flask import request
            query = request.args.get('q', '')
            if not query:
                return jsonify({'error': 'Query parameter "q" required'}), 400
            
            results = self.tool_groups_manager.search_tools(query)
            return jsonify({
                'query': query,
                'count': len(results),
                'results': results
            })
