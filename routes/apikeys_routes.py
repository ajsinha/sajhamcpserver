"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
API Keys Routes for SAJHA MCP Server v2.0.1
Provides full CRUD operations with separate pages (no modals)
"""

from flask import render_template, request, jsonify, redirect, url_for, flash
from routes.base_routes import BaseRoutes
from datetime import datetime


class APIKeysRoutes(BaseRoutes):
    """Routes for API Key management"""

    def __init__(self, auth_manager, tools_registry=None):
        """Initialize API keys routes"""
        super().__init__(auth_manager, tools_registry)

    def register_routes(self, app):
        """Register API key management routes"""

        # =====================================================================
        # Admin Web UI Routes - Separate Pages (No Modals)
        # =====================================================================

        @app.route('/admin/apikeys')
        @self.admin_required
        def admin_apikeys():
            """Admin API keys list page"""
            user_session = self.get_user_session()
            
            # Get all API keys
            apikeys = self.auth_manager.list_api_keys(include_key=False)
            stats = self.auth_manager.get_api_key_statistics()
            
            return render_template('admin/apikeys_list.html',
                                 user=user_session,
                                 apikeys=apikeys,
                                 stats=stats)

        @app.route('/admin/apikeys/create', methods=['GET', 'POST'])
        @self.admin_required
        def admin_apikeys_create():
            """Create new API key page"""
            user_session = self.get_user_session()
            
            # Get available tools for the dropdown
            tools_list = []
            if self.tools_registry:
                tools_list = sorted(self.tools_registry.tools.keys())
            
            if request.method == 'POST':
                # Handle form submission
                name = request.form.get('name', '').strip()
                description = request.form.get('description', '').strip()
                owner = request.form.get('owner', '').strip()
                contact = request.form.get('contact', '').strip()
                purpose = request.form.get('purpose', '').strip()
                expires_at = request.form.get('expires_at', '').strip() or None
                
                tool_access_mode = request.form.get('tool_access_mode', 'all')
                tools = request.form.getlist('tools')
                regex_patterns_raw = request.form.get('regex_patterns', '')
                regex_patterns = [p.strip() for p in regex_patterns_raw.split('\n') if p.strip()]
                
                rate_limit_rpm = request.form.get('rate_limit_rpm', '')
                rate_limit_rph = request.form.get('rate_limit_rph', '')
                
                # Validate
                if not name:
                    return render_template('admin/apikeys_create.html',
                                         user=user_session,
                                         tools_list=tools_list,
                                         error='Name is required',
                                         form_data=request.form)
                
                # Create the key
                success, message, key_data = self.auth_manager.create_api_key(
                    name=name,
                    description=description,
                    created_by=user_session.get('user_id', 'admin'),
                    tool_access_mode=tool_access_mode,
                    tools=tools,
                    regex_patterns=regex_patterns,
                    expires_at=expires_at,
                    rate_limit_rpm=int(rate_limit_rpm) if rate_limit_rpm else None,
                    rate_limit_rph=int(rate_limit_rph) if rate_limit_rph else None,
                    metadata={
                        'owner': owner,
                        'contact': contact,
                        'purpose': purpose
                    }
                )
                
                if success:
                    # Show success page with the full key (only shown once)
                    return render_template('admin/apikeys_created.html',
                                         user=user_session,
                                         apikey=key_data,
                                         message=message)
                else:
                    return render_template('admin/apikeys_create.html',
                                         user=user_session,
                                         tools_list=tools_list,
                                         error=message,
                                         form_data=request.form)
            
            # GET - show create form
            return render_template('admin/apikeys_create.html',
                                 user=user_session,
                                 tools_list=tools_list)

        @app.route('/admin/apikeys/<key>/view')
        @self.admin_required
        def admin_apikeys_view(key):
            """View API key details page"""
            user_session = self.get_user_session()
            
            # Handle partial key lookup
            full_key = self.auth_manager.apikey_manager.get_key_by_partial(key)
            if not full_key:
                return render_template('common/error.html',
                                     error='API Key Not Found',
                                     message=f'The API key "{key}" was not found.'), 404
            
            # Get key data (without full key for security)
            key_data = self.auth_manager.get_api_key(full_key, include_full_key=False)
            
            if not key_data:
                return render_template('common/error.html',
                                     error='API Key Not Found',
                                     message='The API key was not found.'), 404
            
            return render_template('admin/apikeys_view.html',
                                 user=user_session,
                                 apikey=key_data)

        @app.route('/admin/apikeys/<key>/edit', methods=['GET', 'POST'])
        @self.admin_required
        def admin_apikeys_edit(key):
            """Edit API key page"""
            user_session = self.get_user_session()
            
            # Handle partial key lookup
            full_key = self.auth_manager.apikey_manager.get_key_by_partial(key)
            if not full_key:
                return render_template('common/error.html',
                                     error='API Key Not Found',
                                     message=f'The API key "{key}" was not found.'), 404
            
            # Get available tools
            tools_list = []
            if self.tools_registry:
                tools_list = sorted(self.tools_registry.tools.keys())
            
            if request.method == 'POST':
                # Handle form submission
                updates = {}
                
                # Basic info
                name = request.form.get('name', '').strip()
                if name:
                    updates['name'] = name
                
                description = request.form.get('description', '').strip()
                updates['description'] = description
                
                enabled = request.form.get('enabled') == 'on'
                updates['enabled'] = enabled
                
                expires_at = request.form.get('expires_at', '').strip() or None
                updates['expires_at'] = expires_at
                
                # Tool access
                tool_access_mode = request.form.get('tool_access_mode', 'all')
                tools = request.form.getlist('tools')
                regex_patterns_raw = request.form.get('regex_patterns', '')
                regex_patterns = [p.strip() for p in regex_patterns_raw.split('\n') if p.strip()]
                
                updates['tool_access'] = {
                    'mode': tool_access_mode,
                    'tools': tools,
                    'regex_patterns': regex_patterns
                }
                
                # Rate limits
                rate_limit_rpm = request.form.get('rate_limit_rpm', '')
                rate_limit_rph = request.form.get('rate_limit_rph', '')
                updates['rate_limit'] = {
                    'requests_per_minute': int(rate_limit_rpm) if rate_limit_rpm else 60,
                    'requests_per_hour': int(rate_limit_rph) if rate_limit_rph else 1000
                }
                
                # Metadata
                updates['metadata'] = {
                    'owner': request.form.get('owner', '').strip(),
                    'contact': request.form.get('contact', '').strip(),
                    'purpose': request.form.get('purpose', '').strip()
                }
                
                # Update the key
                success, message = self.auth_manager.update_api_key(full_key, updates)
                
                if success:
                    return redirect(url_for('admin_apikeys_view', key=key))
                else:
                    key_data = self.auth_manager.get_api_key(full_key, include_full_key=False)
                    return render_template('admin/apikeys_edit.html',
                                         user=user_session,
                                         apikey=key_data,
                                         tools_list=tools_list,
                                         error=message)
            
            # GET - show edit form
            key_data = self.auth_manager.get_api_key(full_key, include_full_key=False)
            
            if not key_data:
                return render_template('common/error.html',
                                     error='API Key Not Found',
                                     message='The API key was not found.'), 404
            
            return render_template('admin/apikeys_edit.html',
                                 user=user_session,
                                 apikey=key_data,
                                 tools_list=tools_list)

        @app.route('/admin/apikeys/<key>/delete', methods=['GET', 'POST'])
        @self.admin_required
        def admin_apikeys_delete(key):
            """Delete API key confirmation page"""
            user_session = self.get_user_session()
            
            # Handle partial key lookup
            full_key = self.auth_manager.apikey_manager.get_key_by_partial(key)
            if not full_key:
                return render_template('common/error.html',
                                     error='API Key Not Found',
                                     message=f'The API key "{key}" was not found.'), 404
            
            key_data = self.auth_manager.get_api_key(full_key, include_full_key=False)
            
            if request.method == 'POST':
                # Confirm deletion
                success, message = self.auth_manager.delete_api_key(full_key)
                
                if success:
                    return redirect(url_for('admin_apikeys'))
                else:
                    return render_template('admin/apikeys_delete.html',
                                         user=user_session,
                                         apikey=key_data,
                                         error=message)
            
            # GET - show confirmation page
            return render_template('admin/apikeys_delete.html',
                                 user=user_session,
                                 apikey=key_data)

        @app.route('/admin/apikeys/<key>/toggle', methods=['POST'])
        @self.admin_required
        def admin_apikeys_toggle(key):
            """Toggle API key enabled/disabled status"""
            full_key = self.auth_manager.apikey_manager.get_key_by_partial(key)
            if not full_key:
                return redirect(url_for('admin_apikeys'))
            
            key_data = self.auth_manager.get_api_key(full_key, include_full_key=False)
            
            if key_data:
                if key_data.get('enabled', False):
                    self.auth_manager.disable_api_key(full_key)
                else:
                    self.auth_manager.enable_api_key(full_key)
            
            return redirect(url_for('admin_apikeys'))

        # =====================================================================
        # API Endpoints for API Key Management
        # =====================================================================

        @app.route('/api/admin/apikeys', methods=['GET'])
        @self.admin_required
        def api_list_apikeys():
            """List all API keys"""
            include_key = request.args.get('include_key', 'false').lower() == 'true'
            apikeys = self.auth_manager.list_api_keys(include_key=include_key)
            
            return jsonify({
                'success': True,
                'apikeys': apikeys,
                'count': len(apikeys)
            })

        @app.route('/api/admin/apikeys', methods=['POST'])
        @self.admin_required
        def api_create_apikey():
            """Create a new API key"""
            user_session = self.get_user_session()
            data = request.get_json()
            
            if not data:
                return jsonify({'success': False, 'error': 'No data provided'}), 400
            
            name = data.get('name')
            if not name:
                return jsonify({'success': False, 'error': 'Name is required'}), 400
            
            # Parse tool access configuration
            tool_access_mode = data.get('tool_access_mode', 'all')
            tools = data.get('tools', [])
            regex_patterns = data.get('regex_patterns', [])
            
            # Parse if tools/patterns are strings (comma-separated)
            if isinstance(tools, str):
                tools = [t.strip() for t in tools.split(',') if t.strip()]
            if isinstance(regex_patterns, str):
                regex_patterns = [p.strip() for p in regex_patterns.split('\n') if p.strip()]
            
            success, message, key_data = self.auth_manager.create_api_key(
                name=name,
                description=data.get('description', ''),
                created_by=user_session.get('user_id', 'admin'),
                tool_access_mode=tool_access_mode,
                tools=tools,
                regex_patterns=regex_patterns,
                expires_at=data.get('expires_at'),
                rate_limit_rpm=data.get('rate_limit_rpm'),
                rate_limit_rph=data.get('rate_limit_rph'),
                metadata={
                    'owner': data.get('owner', ''),
                    'contact': data.get('contact', ''),
                    'purpose': data.get('purpose', '')
                }
            )
            
            if success:
                return jsonify({
                    'success': True,
                    'message': message,
                    'apikey': key_data
                })
            else:
                return jsonify({
                    'success': False,
                    'error': message
                }), 400

        @app.route('/api/admin/apikeys/<key>', methods=['GET'])
        @self.admin_required
        def api_get_apikey(key):
            """Get a specific API key's details"""
            include_full = request.args.get('include_full', 'false').lower() == 'true'
            
            # Handle partial key lookup
            full_key = self.auth_manager.apikey_manager.get_key_by_partial(key)
            if not full_key:
                return jsonify({'success': False, 'error': 'API key not found'}), 404
            
            key_data = self.auth_manager.get_api_key(full_key, include_full_key=include_full)
            
            if key_data:
                return jsonify({
                    'success': True,
                    'apikey': key_data
                })
            else:
                return jsonify({
                    'success': False,
                    'error': 'API key not found'
                }), 404

        @app.route('/api/admin/apikeys/<key>', methods=['PUT'])
        @self.admin_required
        def api_update_apikey(key):
            """Update an API key"""
            data = request.get_json()
            
            if not data:
                return jsonify({'success': False, 'error': 'No data provided'}), 400
            
            # Handle partial key lookup
            full_key = self.auth_manager.apikey_manager.get_key_by_partial(key)
            if not full_key:
                return jsonify({'success': False, 'error': 'API key not found'}), 404
            
            # Build updates dictionary
            updates = {}
            
            if 'name' in data:
                updates['name'] = data['name']
            if 'description' in data:
                updates['description'] = data['description']
            if 'enabled' in data:
                updates['enabled'] = data['enabled']
            if 'expires_at' in data:
                updates['expires_at'] = data['expires_at']
            
            # Handle tool access
            if any(k in data for k in ['tool_access_mode', 'tools', 'regex_patterns']):
                current_key = self.auth_manager.get_api_key(full_key, include_full_key=True)
                tool_access = current_key.get('tool_access', {}) if current_key else {}
                
                if 'tool_access_mode' in data:
                    tool_access['mode'] = data['tool_access_mode']
                
                if 'tools' in data:
                    tools = data['tools']
                    if isinstance(tools, str):
                        tools = [t.strip() for t in tools.split(',') if t.strip()]
                    tool_access['tools'] = tools
                
                if 'regex_patterns' in data:
                    patterns = data['regex_patterns']
                    if isinstance(patterns, str):
                        patterns = [p.strip() for p in patterns.split('\n') if p.strip()]
                    tool_access['regex_patterns'] = patterns
                
                updates['tool_access'] = tool_access
            
            # Handle rate limits
            if 'rate_limit_rpm' in data or 'rate_limit_rph' in data:
                current_key = self.auth_manager.get_api_key(full_key, include_full_key=True)
                rate_limit = current_key.get('rate_limit', {}) if current_key else {}
                
                if 'rate_limit_rpm' in data:
                    rate_limit['requests_per_minute'] = data['rate_limit_rpm']
                if 'rate_limit_rph' in data:
                    rate_limit['requests_per_hour'] = data['rate_limit_rph']
                
                updates['rate_limit'] = rate_limit
            
            # Handle metadata
            if any(k in data for k in ['owner', 'contact', 'purpose']):
                current_key = self.auth_manager.get_api_key(full_key, include_full_key=True)
                metadata = current_key.get('metadata', {}) if current_key else {}
                
                if 'owner' in data:
                    metadata['owner'] = data['owner']
                if 'contact' in data:
                    metadata['contact'] = data['contact']
                if 'purpose' in data:
                    metadata['purpose'] = data['purpose']
                
                updates['metadata'] = metadata
            
            success, message = self.auth_manager.update_api_key(full_key, updates)
            
            if success:
                return jsonify({
                    'success': True,
                    'message': message
                })
            else:
                return jsonify({
                    'success': False,
                    'error': message
                }), 400

        @app.route('/api/admin/apikeys/<key>', methods=['DELETE'])
        @self.admin_required
        def api_delete_apikey(key):
            """Delete an API key"""
            # Handle partial key lookup
            full_key = self.auth_manager.apikey_manager.get_key_by_partial(key)
            if not full_key:
                return jsonify({'success': False, 'error': 'API key not found'}), 404
            
            success, message = self.auth_manager.delete_api_key(full_key)
            
            if success:
                return jsonify({
                    'success': True,
                    'message': message
                })
            else:
                return jsonify({
                    'success': False,
                    'error': message
                }), 400

        @app.route('/api/admin/apikeys/<key>/enable', methods=['POST'])
        @self.admin_required
        def api_enable_apikey(key):
            """Enable an API key"""
            full_key = self.auth_manager.apikey_manager.get_key_by_partial(key)
            if not full_key:
                return jsonify({'success': False, 'error': 'API key not found'}), 404
            
            success, message = self.auth_manager.enable_api_key(full_key)
            
            return jsonify({
                'success': success,
                'message': message if success else None,
                'error': message if not success else None
            })

        @app.route('/api/admin/apikeys/<key>/disable', methods=['POST'])
        @self.admin_required
        def api_disable_apikey(key):
            """Disable an API key"""
            full_key = self.auth_manager.apikey_manager.get_key_by_partial(key)
            if not full_key:
                return jsonify({'success': False, 'error': 'API key not found'}), 404
            
            success, message = self.auth_manager.disable_api_key(full_key)
            
            return jsonify({
                'success': success,
                'message': message if success else None,
                'error': message if not success else None
            })

        @app.route('/api/admin/apikeys/stats', methods=['GET'])
        @self.admin_required
        def api_apikey_stats():
            """Get API key statistics"""
            stats = self.auth_manager.get_api_key_statistics()
            
            return jsonify({
                'success': True,
                'stats': stats
            })

        # =====================================================================
        # Public API Authentication Endpoint
        # =====================================================================

        @app.route('/api/auth/token', methods=['POST'])
        def api_get_token():
            """
            Get authentication token using basic credentials.
            Accepts username as: uid, username, user_name, user_id
            Accepts password as: password
            
            Returns a Bearer token for subsequent API requests.
            """
            data = request.get_json()
            
            if not data:
                return jsonify({
                    'success': False,
                    'error': 'No credentials provided'
                }), 400
            
            success, token, message = self.auth_manager.authenticate_basic(data)
            
            if success:
                return jsonify({
                    'success': True,
                    'token': token,
                    'token_type': 'Bearer',
                    'message': message
                })
            else:
                return jsonify({
                    'success': False,
                    'error': message
                }), 401

        @app.route('/api/auth/validate', methods=['POST'])
        def api_validate_auth():
            """Validate current authentication (Bearer token or API key)"""
            auth_result = self.auth_manager.authenticate_request(request)
            
            if auth_result.get('authenticated'):
                return jsonify({
                    'success': True,
                    'authenticated': True,
                    'auth_type': auth_result.get('auth_type'),
                    'user_id': auth_result.get('user_id'),
                    'roles': auth_result.get('roles', [])
                })
            else:
                return jsonify({
                    'success': False,
                    'authenticated': False,
                    'error': auth_result.get('error', 'Authentication failed')
                }), 401
