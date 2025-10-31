"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
API Routes for SAJHA MCP Server
"""

import logging
import csv
import io
import os
from pathlib import Path
from flask import request, jsonify, make_response
from datetime import datetime
from routes.base_routes import BaseRoutes


class ApiRoutes(BaseRoutes):
    """API endpoints for programmatic access"""

    def __init__(self, auth_manager, tools_registry, mcp_handler):
        """Initialize API routes"""
        super().__init__(auth_manager, tools_registry, mcp_handler)

    def register_routes(self, app):
        """Register API routes"""

        # ==================== MCP Protocol Endpoint ====================
        @app.route('/api/mcp', methods=['POST'])
        def mcp_endpoint():
            """MCP protocol endpoint for HTTP requests"""
            # Get authorization header
            auth_header = request.headers.get('Authorization', '')

            # Validate token
            session_data = None
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]
                session_data = self.auth_manager.validate_session(token)

            # Get request data
            try:
                request_data = request.get_json()
            except:
                return jsonify({
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32700,
                        "message": "Parse error"
                    }
                }), 400

            # Handle request
            response = self.mcp_handler.handle_request(request_data, session_data)
            return jsonify(response)

        # ==================== Authentication Endpoints ====================
        @app.route('/api/auth/login', methods=['POST'])
        def api_login():
            """API login endpoint"""
            data = request.get_json()
            user_id = data.get('user_id')
            password = data.get('password')

            if not user_id or not password:
                return jsonify({'error': 'Missing credentials'}), 400

            token = self.auth_manager.authenticate(user_id, password)
            if token:
                session_data = self.auth_manager.validate_session(token)
                return jsonify({
                    'token': token,
                    'user': {
                        'user_id': session_data['user_id'],
                        'user_name': session_data['user_name'],
                        'roles': session_data['roles']
                    }
                })
            else:
                return jsonify({'error': 'Invalid credentials'}), 401

        # ==================== Tools Execution Endpoints ====================
        @app.route('/api/tools/execute', methods=['POST'])
        def api_tool_execute():
            """API endpoint for tool execution"""
            # Get authorization
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                return jsonify({'error': 'Unauthorized'}), 401

            token = auth_header[7:]
            session_data = self.auth_manager.validate_session(token)
            if not session_data:
                return jsonify({'error': 'Invalid token'}), 401

            # Get request data
            data = request.get_json()
            tool_name = data.get('tool')
            arguments = data.get('arguments', {})

            # Check access
            if not self.auth_manager.has_tool_access(session_data, tool_name):
                return jsonify({'error': 'Access denied'}), 403

            # Execute tool
            try:
                tool = self.tools_registry.get_tool(tool_name)
                if not tool:
                    return jsonify({'error': 'Tool not found'}), 404

                result = tool.execute_with_tracking(arguments)
                return jsonify({
                    'success': True,
                    'result': result
                })
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': str(e)
                }), 500

        @app.route('/api/tools/list', methods=['GET'])
        @self.login_required
        def api_tools_list():
            """Get list of all tools"""
            try:
                tools = self.tools_registry.get_all_tools()
                return jsonify({'tools': tools})
            except Exception as e:
                logging.error(f"Error getting tools list: {e}")
                return jsonify({'error': str(e)}), 500

        @app.route('/api/tools/<tool_name>/schema', methods=['GET'])
        @self.login_required
        def api_get_tool_schema(tool_name):
            """Get tool input schema"""
            try:
                user_session = self.get_user_session()

                # Check if user has access to this tool
                if not self.auth_manager.has_tool_access(user_session, tool_name):
                    return jsonify({'error': 'Access denied'}), 403

                # Get tool
                tool = self.tools_registry.get_tool(tool_name)
                if not tool:
                    return jsonify({'error': 'Tool not found'}), 404

                # Return tool schema in MCP format
                return jsonify(tool.to_mcp_format())

            except Exception as e:
                logging.error(f"Error getting tool schema: {e}")
                return jsonify({'error': str(e)}), 500

        # ==================== Admin Tools Management ====================
        @app.route('/api/admin/tools/<tool_name>/enable', methods=['POST'])
        @self.admin_required
        def api_enable_tool(tool_name):
            """Enable a tool"""
            success = self.tools_registry.enable_tool(tool_name)
            if success:
                return jsonify({'success': True})
            else:
                return jsonify({'error': 'Tool not found'}), 404

        @app.route('/api/admin/tools/<tool_name>/disable', methods=['POST'])
        @self.admin_required
        def api_disable_tool(tool_name):
            """Disable a tool"""
            success = self.tools_registry.disable_tool(tool_name)
            if success:
                return jsonify({'success': True})
            else:
                return jsonify({'error': 'Tool not found'}), 404

        @app.route('/api/admin/tools/metrics/export')
        @self.admin_required
        def api_export_metrics():
            """Export tool metrics as CSV"""
            try:
                # Get all tool metrics
                metrics = self.tools_registry.get_tool_metrics()

                # Create CSV in memory
                output = io.StringIO()
                writer = csv.writer(output)

                # Write header
                writer.writerow([
                    'Tool Name',
                    'Version',
                    'Status',
                    'Execution Count',
                    'Average Execution Time (s)',
                    'Last Execution',
                    'Description'
                ])

                # Write data
                for metric in metrics:
                    writer.writerow([
                        metric.get('name', ''),
                        metric.get('version', ''),
                        'Enabled' if metric.get('enabled', False) else 'Disabled',
                        metric.get('execution_count', 0),
                        f"{metric.get('average_execution_time', 0):.3f}",
                        metric.get('last_execution', 'Never'),
                        metric.get('description', '')
                    ])

                # Prepare response
                output.seek(0)
                response = make_response(output.getvalue())
                response.headers['Content-Type'] = 'text/csv'
                response.headers['Content-Disposition'] = f'attachment; filename=tool_metrics_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

                return response

            except Exception as e:
                logging.error(f"Error exporting metrics: {e}")
                return jsonify({'error': 'Failed to export metrics'}), 500

        @app.route('/api/admin/tools/<tool_name>/config', methods=['GET'])
        @self.admin_required
        def api_get_tool_config(tool_name):
            """Get tool configuration"""
            try:
                # First try to get from tool_configs
                if tool_name in self.tools_registry.tool_configs:
                    return jsonify(self.tools_registry.tool_configs[tool_name])

                # Otherwise get from tool instance
                tool = self.tools_registry.get_tool(tool_name)
                if tool:
                    return jsonify(tool.config)

                return jsonify({'error': 'Tool not found'}), 404

            except Exception as e:
                logging.error(f"Error getting tool config: {e}")
                return jsonify({'error': str(e)}), 500

        @app.route('/api/admin/tools/<tool_name>/config', methods=['POST'])
        @self.admin_required
        def api_save_tool_config(tool_name):
            """Save tool configuration"""
            try:
                config = request.get_json()

                if not config:
                    return jsonify({'error': 'No configuration provided'}), 400

                # Validate required fields
                required_fields = ['name', 'description', 'version', 'enabled', 'inputSchema']
                for field in required_fields:
                    if field not in config:
                        return jsonify({'error': f'Missing required field: {field}'}), 400

                # Ensure name matches
                if config['name'] != tool_name:
                    return jsonify({'error': 'Tool name in configuration does not match'}), 400

                # Update the tool configuration
                self.tools_registry.tool_configs[tool_name] = config

                # Save to file
                self.tools_registry._save_tool_config(tool_name)

                # If tool is already loaded, unregister and reload it
                if tool_name in self.tools_registry.tools:
                    self.tools_registry.unregister_tool(tool_name)

                # Reload the tool with new config
                config_file = Path(self.tools_registry.tools_config_dir) / f"{tool_name}.json"
                if config_file.exists():
                    self.tools_registry.load_tool_from_config(config_file)

                return jsonify({
                    'success': True,
                    'message': 'Configuration saved successfully'
                })

            except Exception as e:
                logging.error(f"Error saving tool config: {e}")
                return jsonify({'error': str(e)}), 500

        @app.route('/api/admin/tools/<tool_name>/delete', methods=['DELETE'])
        @self.admin_required
        def api_delete_tool(tool_name):
            """Delete a tool configuration"""
            try:
                # Unregister tool if loaded
                if tool_name in self.tools_registry.tools:
                    self.tools_registry.unregister_tool(tool_name)

                # Remove from configs
                if tool_name in self.tools_registry.tool_configs:
                    del self.tools_registry.tool_configs[tool_name]

                # Delete configuration file
                config_file = Path(self.tools_registry.tools_config_dir) / f"{tool_name}.json"
                if config_file.exists():
                    os.remove(config_file)

                return jsonify({
                    'success': True,
                    'message': f'Tool {tool_name} deleted successfully'
                })

            except Exception as e:
                logging.error(f"Error deleting tool: {e}")
                return jsonify({'error': str(e)}), 500

        @app.route('/api/admin/tools/reload', methods=['POST'])
        @self.admin_required
        def api_reload_tools():
            """Reload all tools from configuration"""
            try:
                self.tools_registry.reload_all_tools()
                return jsonify({
                    'success': True,
                    'message': 'Tools reloaded successfully'
                })
            except Exception as e:
                logging.error(f"Error reloading tools: {e}")
                return jsonify({'error': str(e)}), 500

        # ==================== Admin User Management ====================
        @app.route('/api/admin/users/<user_id>/config', methods=['GET'])
        @self.admin_required
        def api_get_user_config(user_id):
            """Get user configuration"""
            try:
                user_data = self.auth_manager.get_user(user_id)
                if not user_data:
                    return jsonify({'error': 'User not found'}), 404

                return jsonify(user_data)

            except Exception as e:
                logging.error(f"Error getting user config: {e}")
                return jsonify({'error': str(e)}), 500

        @app.route('/api/admin/users/<user_id>/config', methods=['POST'])
        @self.admin_required
        def api_save_user_config(user_id):
            """Save user configuration"""
            try:
                config = request.get_json()

                if not config:
                    return jsonify({'error': 'No configuration provided'}), 400

                # Validate required fields
                required_fields = ['user_id', 'user_name', 'enabled']
                for field in required_fields:
                    if field not in config:
                        return jsonify({'error': f'Missing required field: {field}'}), 400

                # Ensure user_id matches
                if config['user_id'] != user_id:
                    return jsonify({'error': 'User ID in configuration does not match'}), 400

                # Update user
                success = self.auth_manager.update_user(user_id, config)

                if success:
                    return jsonify({
                        'success': True,
                        'message': 'User configuration saved successfully'
                    })
                else:
                    return jsonify({'error': 'Failed to update user'}), 500

            except Exception as e:
                logging.error(f"Error saving user config: {e}")
                return jsonify({'error': str(e)}), 500

        @app.route('/api/admin/users/<user_id>/enable', methods=['POST'])
        @self.admin_required
        def api_enable_user(user_id):
            """Enable a user"""
            try:
                success = self.auth_manager.enable_user(user_id)
                if success:
                    return jsonify({'success': True})
                else:
                    return jsonify({'error': 'User not found'}), 404
            except Exception as e:
                logging.error(f"Error enabling user: {e}")
                return jsonify({'error': str(e)}), 500

        @app.route('/api/admin/users/<user_id>/disable', methods=['POST'])
        @self.admin_required
        def api_disable_user(user_id):
            """Disable a user"""
            try:
                if user_id == 'admin':
                    return jsonify({'error': 'Cannot disable admin user'}), 400

                success = self.auth_manager.disable_user(user_id)
                if success:
                    return jsonify({'success': True})
                else:
                    return jsonify({'error': 'User not found'}), 404
            except Exception as e:
                logging.error(f"Error disabling user: {e}")
                return jsonify({'error': str(e)}), 500

        @app.route('/api/admin/users/<user_id>/delete', methods=['DELETE'])
        @self.admin_required
        def api_delete_user(user_id):
            """Delete a user"""
            try:
                if user_id == 'admin':
                    return jsonify({'error': 'Cannot delete admin user'}), 400

                success = self.auth_manager.delete_user(user_id)

                if success:
                    return jsonify({
                        'success': True,
                        'message': f'User {user_id} deleted successfully'
                    })
                else:
                    return jsonify({'error': 'User not found'}), 404

            except Exception as e:
                logging.error(f"Error deleting user: {e}")
                return jsonify({'error': str(e)}), 500

        @app.route('/api/admin/users/create', methods=['POST'])
        @self.admin_required
        def api_create_user():
            """Create a new user"""
            try:
                user_data = request.get_json()

                if not user_data:
                    return jsonify({'error': 'No user data provided'}), 400

                # Validate required fields
                required_fields = ['user_id', 'user_name', 'password']
                for field in required_fields:
                    if field not in user_data:
                        return jsonify({'error': f'Missing required field: {field}'}), 400

                # Check if user already exists
                if self.auth_manager.get_user(user_data['user_id']):
                    return jsonify({'error': 'User already exists'}), 409

                # Set defaults
                if 'enabled' not in user_data:
                    user_data['enabled'] = True
                if 'roles' not in user_data:
                    user_data['roles'] = ['user']
                if 'tools' not in user_data:
                    user_data['tools'] = ['*']
                if 'created_at' not in user_data:
                    user_data['created_at'] = datetime.now().isoformat() + 'Z'

                # Create user
                success = self.auth_manager.create_user(user_data)

                if success:
                    return jsonify({
                        'success': True,
                        'message': 'User created successfully',
                        'user_id': user_data['user_id']
                    })
                else:
                    return jsonify({'error': 'Failed to create user'}), 500

            except Exception as e:
                logging.error(f"Error creating user: {e}")
                return jsonify({'error': str(e)}), 500

        @app.route('/api/admin/users/export')
        @self.admin_required
        def api_export_users():
            """Export all users as CSV"""
            try:
                users = self.auth_manager.get_all_users()

                # Create CSV in memory
                output = io.StringIO()
                writer = csv.writer(output)

                # Write header
                writer.writerow([
                    'User ID',
                    'Name',
                    'Email',
                    'Roles',
                    'Status',
                    'Tools Access',
                    'Created At',
                    'Last Login'
                ])

                # Write data
                for user_data in users:
                    writer.writerow([
                        user_data.get('user_id', ''),
                        user_data.get('user_name', ''),
                        user_data.get('email', ''),
                        ','.join(user_data.get('roles', [])),
                        'Enabled' if user_data.get('enabled', False) else 'Disabled',
                        ','.join(user_data.get('tools', [])),
                        user_data.get('created_at', ''),
                        user_data.get('last_login', 'Never')
                    ])

                # Prepare response
                output.seek(0)
                response = make_response(output.getvalue())
                response.headers['Content-Type'] = 'text/csv'
                response.headers['Content-Disposition'] = f'attachment; filename=users_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

                return response

            except Exception as e:
                logging.error(f"Error exporting users: {e}")
                return jsonify({'error': 'Failed to export users'}), 500