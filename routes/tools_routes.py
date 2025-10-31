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

        @app.route('/tools/<tool_name>/schema')
        @self.login_required
        def tool_schema(tool_name):
            """Tool schema display page"""
            user_session = self.get_user_session()

            # Check if user has access to this tool
            if not self.auth_manager.has_tool_access(user_session, tool_name):
                return render_template('error.html',
                                     error="Access Denied",
                                     message=f"You don't have permission to view {tool_name}"), 403

            # Get tool details
            tool = self.tools_registry.get_tool(tool_name)
            if not tool:
                return render_template('error.html',
                                     error="Tool Not Found",
                                     message=f"Tool {tool_name} not found"), 404

            # Get tool data in MCP format
            tool_data = tool.to_mcp_format()

            # Import json for pretty printing
            import json
            schema_json = json.dumps(tool_data, indent=2)

            # Load tool configuration from config/tools folder
            config_json = None
            try:
                from pathlib import Path
                config_file = Path(self.tools_registry.tools_config_dir) / f"{tool_name}.json"
                if config_file.exists():
                    with open(config_file, 'r') as f:
                        config_data = json.load(f)
                    config_json = json.dumps(config_data, indent=2)
            except Exception as e:
                config_json = f"Error loading configuration: {str(e)}"

            # Load literature content from config/literature folder
            literature_content = ""
            try:
                from pathlib import Path
                # Assume config/literature is at the same level as config/tools
                config_dir = Path(self.tools_registry.tools_config_dir).parent
                literature_file = config_dir / 'literature' / f"{tool_name}.txt"
                if literature_file.exists():
                    with open(literature_file, 'r', encoding='utf-8') as f:
                        literature_content = f.read()
            except Exception as e:
                literature_content = ""

            return render_template('tool_schema.html',
                                 user=user_session,
                                 tool=tool_data,
                                 schema_json=schema_json,
                                 config_json=config_json,
                                 literature_content=literature_content)

        @app.route('/tools/<tool_name>/literature/save', methods=['POST'])
        @self.login_required
        def save_tool_literature(tool_name):
            """Save literature content for a tool"""
            user_session = self.get_user_session()

            # Check if user has access to this tool
            if not self.auth_manager.has_tool_access(user_session, tool_name):
                from flask import jsonify
                return jsonify({
                    'success': False,
                    'error': 'Access denied'
                }), 403

            # Get tool details to verify it exists
            tool = self.tools_registry.get_tool(tool_name)
            if not tool:
                from flask import jsonify
                return jsonify({
                    'success': False,
                    'error': 'Tool not found'
                }), 404

            try:
                from flask import request
                from pathlib import Path
                import os

                # Get the literature content from request
                literature_content = request.form.get('literature_content', '')

                # Determine literature file path
                config_dir = Path(self.tools_registry.tools_config_dir).parent
                literature_dir = config_dir / 'literature'

                # Create literature directory if it doesn't exist
                literature_dir.mkdir(parents=True, exist_ok=True)

                literature_file = literature_dir / f"{tool_name}.txt"

                # Write the content to file
                with open(literature_file, 'w', encoding='utf-8') as f:
                    f.write(literature_content)

                from flask import jsonify
                return jsonify({
                    'success': True,
                    'message': 'Literature content saved successfully'
                })

            except Exception as e:
                from flask import jsonify
                return jsonify({
                    'success': False,
                    'error': f'Error saving literature: {str(e)}'
                }), 500

        @app.route('/tooljson/list')
        @self.login_required
        def tools_list_json():
            """Get list of all tools in JSON format"""
            user_session = self.get_user_session()

            # Get all tools
            tools = self.tools_registry.get_all_tools()

            # Filter based on user permissions
            accessible_tools = self.auth_manager.get_user_accessible_tools(user_session)
            if '*' not in accessible_tools:
                tools = [t for t in tools if t['name'] in accessible_tools]

            from flask import jsonify
            return jsonify({
                'success': True,
                'count': len(tools),
                'tools': tools
            })

        @app.route('/tooljson/<tool_name>')
        @self.login_required
        def tool_json(tool_name):
            """Get tool schema and config in JSON format"""
            user_session = self.get_user_session()

            # Check if user has access to this tool
            if not self.auth_manager.has_tool_access(user_session, tool_name):
                from flask import jsonify
                return jsonify({
                    'success': False,
                    'error': 'Access denied'
                }), 403

            # Get tool details
            tool = self.tools_registry.get_tool(tool_name)
            if not tool:
                from flask import jsonify
                return jsonify({
                    'success': False,
                    'error': 'Tool not found'
                }), 404

            # Get tool schema
            tool_schema = tool.to_mcp_format()

            # Load tool configuration from config/tools folder
            tool_config = None
            try:
                import json
                from pathlib import Path
                config_file = Path(self.tools_registry.tools_config_dir) / f"{tool_name}.json"
                if config_file.exists():
                    with open(config_file, 'r') as f:
                        tool_config = json.load(f)
            except Exception as e:
                tool_config = {'error': f'Error loading configuration: {str(e)}'}

            # Load literature content from config/literature folder
            literature_content = ""
            try:
                from pathlib import Path
                # Assume config/literature is at the same level as config/tools
                config_dir = Path(self.tools_registry.tools_config_dir).parent
                literature_file = config_dir / 'literature' / f"{tool_name}.txt"
                if literature_file.exists():
                    with open(literature_file, 'r', encoding='utf-8') as f:
                        literature_content = f.read()
            except Exception as e:
                # If there's an error reading literature, just leave it empty
                literature_content = ""

            from flask import jsonify
            return jsonify({
                'success': True,
                'tool_name': tool_name,
                'schema': tool_schema,
                'config': tool_config,
                'literature': literature_content
            })

        @app.route('/tooljsonall')
        @self.login_required
        def tools_all_json_list():
            """Get all tools with their schemas and configs in JSON array format"""
            user_session = self.get_user_session()

            # Get all tools
            all_tools = self.tools_registry.get_all_tools()

            # Filter based on user permissions
            accessible_tools = self.auth_manager.get_user_accessible_tools(user_session)
            if '*' not in accessible_tools:
                all_tools = [t for t in all_tools if t['name'] in accessible_tools]

            # Build the comprehensive tools list
            tools_json_list = []

            import json
            from pathlib import Path

            for tool_info in all_tools:
                tool_name = tool_info['name']

                # Get tool instance
                tool = self.tools_registry.get_tool(tool_name)
                if not tool:
                    continue

                # Get tool schema
                tool_schema = tool.to_mcp_format()

                # Load tool configuration from config/tools folder
                tool_config = None
                try:
                    config_file = Path(self.tools_registry.tools_config_dir) / f"{tool_name}.json"
                    if config_file.exists():
                        with open(config_file, 'r') as f:
                            tool_config = json.load(f)
                except Exception as e:
                    tool_config = {'error': f'Error loading configuration: {str(e)}'}

                # Load literature content from config/literature folder
                literature_content = ""
                try:
                    # Assume config/literature is at the same level as config/tools
                    config_dir = Path(self.tools_registry.tools_config_dir).parent
                    literature_file = config_dir / 'literature' / f"{tool_name}.txt"
                    if literature_file.exists():
                        with open(literature_file, 'r', encoding='utf-8') as f:
                            literature_content = f.read()
                except Exception as e:
                    # If there's an error reading literature, just leave it empty
                    literature_content = ""

                # Add to list
                tools_json_list.append({
                    tool_name: {
                        'schema': tool_schema,
                        'config': tool_config,
                        'literature': literature_content
                    }
                })

            from flask import jsonify
            return jsonify({
                'success': True,
                'count': len(tools_json_list),
                'tools': tools_json_list
            })

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