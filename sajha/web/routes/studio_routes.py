"""
SAJHA MCP Server - MCP Studio Routes v2.8.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Routes for the MCP Studio feature - admin-only tool creation interface.
Supports Python code-based, REST service-based, DB Query-based, Script-based,
PowerBI report, PowerBI DAX query, and IBM LiveLink document tool creation.
"""

import json
import logging
from flask import request, render_template, jsonify, flash, redirect, url_for
from .base_routes import BaseRoutes

from sajha.studio import CodeAnalyzer, ToolCodeGenerator, ToolDefinition
from sajha.studio import RESTToolGenerator, RESTToolDefinition
from sajha.studio import DBQueryToolGenerator, DBQueryToolDefinition, DBQueryParameter
from sajha.studio import ScriptToolGenerator, ScriptToolConfig
from sajha.studio import PowerBIToolGenerator, PowerBIToolConfig
from sajha.studio import PowerBIDAXToolGenerator, PowerBIDAXToolConfig
from sajha.studio import LiveLinkToolGenerator, LiveLinkToolConfig

logger = logging.getLogger(__name__)


class StudioRoutes(BaseRoutes):
    """Routes for MCP Studio - visual tool creation."""
    
    def __init__(self, auth_manager, tools_registry):
        """
        Initialize Studio routes.
        
        Args:
            auth_manager: AuthManager instance
            tools_registry: ToolsRegistry instance
        """
        super().__init__(auth_manager, tools_registry, None)
        self.analyzer = CodeAnalyzer()
        self.generator = ToolCodeGenerator()
        self.rest_generator = RESTToolGenerator()
        self.dbquery_generator = DBQueryToolGenerator()
        
        # Initialize script generator with proper paths
        import os
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.script_generator = ScriptToolGenerator(
            config_dir=os.path.join(base_dir, 'config', 'tools'),
            scripts_dir=os.path.join(base_dir, 'config', 'scripts'),
            impl_dir=os.path.join(base_dir, 'sajha', 'tools', 'impl')
        )
        
        # Initialize PowerBI generator with proper paths
        self.powerbi_generator = PowerBIToolGenerator(
            config_dir=os.path.join(base_dir, 'config', 'tools'),
            impl_dir=os.path.join(base_dir, 'sajha', 'tools', 'impl')
        )
        
        # Initialize PowerBI DAX generator with proper paths
        self.powerbidax_generator = PowerBIDAXToolGenerator(
            config_dir=os.path.join(base_dir, 'config', 'tools'),
            impl_dir=os.path.join(base_dir, 'sajha', 'tools', 'impl')
        )
        
        # Initialize LiveLink generator with proper paths
        self.livelink_generator = LiveLinkToolGenerator(
            config_dir=os.path.join(base_dir, 'config', 'tools'),
            impl_dir=os.path.join(base_dir, 'sajha', 'tools', 'impl')
        )
    
    def register_routes(self, app):
        """Register MCP Studio routes."""
        
        @app.route('/admin/studio')
        @self.admin_required
        def studio_home():
            """MCP Studio main page."""
            user_session = self.get_user_session()
            # Get list of existing tools for conflict detection
            existing_tools = list(self.tools_registry.tools.keys())
            
            return render_template('admin/studio/studio_home.html',
                                 user=user_session,
                                 existing_tools=existing_tools,
                                 sample_code=self._get_sample_code())
        
        @app.route('/admin/studio/rest')
        @self.admin_required
        def studio_rest():
            """REST Service Tool Creator page."""
            user_session = self.get_user_session()
            existing_tools = list(self.tools_registry.tools.keys())
            
            return render_template('admin/studio/studio_rest.html',
                                 user=user_session,
                                 existing_tools=existing_tools)
        
        @app.route('/admin/studio/rest/preview', methods=['POST'])
        @self.admin_required
        def studio_rest_preview():
            """Preview REST tool generation."""
            try:
                data = request.get_json()
                
                # Create definition from request data
                definition = RESTToolDefinition(
                    name=data.get('name', '').strip().lower(),
                    endpoint=data.get('endpoint', ''),
                    method=data.get('method', 'GET'),
                    description=data.get('description', ''),
                    request_schema=data.get('request_schema', {}),
                    response_schema=data.get('response_schema', {}),
                    category=data.get('category', 'REST API'),
                    tags=data.get('tags', []),
                    api_key=data.get('api_key'),
                    api_key_header=data.get('api_key_header', 'X-API-Key'),
                    basic_auth_username=data.get('basic_auth_username'),
                    basic_auth_password=data.get('basic_auth_password'),
                    headers=data.get('headers', {}),
                    timeout=data.get('timeout', 30),
                    content_type=data.get('content_type', 'application/json'),
                    response_format=data.get('response_format', 'json'),
                    csv_delimiter=data.get('csv_delimiter', ','),
                    csv_has_header=data.get('csv_has_header', True),
                    csv_skip_rows=data.get('csv_skip_rows', 0)
                )
                
                # Check for name conflicts
                existing_tools = list(self.tools_registry.tools.keys())
                if definition.name in existing_tools:
                    return jsonify({
                        'success': False,
                        'error': f'Tool "{definition.name}" already exists'
                    }), 400
                
                # Generate preview
                preview = self.rest_generator.preview_tool(definition)
                
                if not preview.get('success'):
                    return jsonify({
                        'success': False,
                        'error': 'Validation errors: ' + ', '.join(preview.get('errors', []))
                    }), 400
                
                return jsonify({
                    'success': True,
                    'json_content': preview['json_content'],
                    'python_content': preview['python_content'],
                    'json_filename': preview['json_filename'],
                    'python_filename': preview['python_filename']
                })
                
            except Exception as e:
                logger.error(f"Error previewing REST tool: {e}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': f'Preview error: {str(e)}'
                }), 500
        
        @app.route('/admin/studio/rest/deploy', methods=['POST'])
        @self.admin_required
        def studio_rest_deploy():
            """Deploy REST tool."""
            try:
                data = request.get_json()
                
                # Create definition from request data
                definition = RESTToolDefinition(
                    name=data.get('name', '').strip().lower(),
                    endpoint=data.get('endpoint', ''),
                    method=data.get('method', 'GET'),
                    description=data.get('description', ''),
                    request_schema=data.get('request_schema', {}),
                    response_schema=data.get('response_schema', {}),
                    category=data.get('category', 'REST API'),
                    tags=data.get('tags', []),
                    api_key=data.get('api_key'),
                    api_key_header=data.get('api_key_header', 'X-API-Key'),
                    basic_auth_username=data.get('basic_auth_username'),
                    basic_auth_password=data.get('basic_auth_password'),
                    headers=data.get('headers', {}),
                    timeout=data.get('timeout', 30),
                    content_type=data.get('content_type', 'application/json'),
                    response_format=data.get('response_format', 'json'),
                    csv_delimiter=data.get('csv_delimiter', ','),
                    csv_has_header=data.get('csv_has_header', True),
                    csv_skip_rows=data.get('csv_skip_rows', 0)
                )
                
                # Check for name conflicts
                existing_tools = list(self.tools_registry.tools.keys())
                if definition.name in existing_tools:
                    return jsonify({
                        'success': False,
                        'error': f'Tool "{definition.name}" already exists'
                    }), 400
                
                # Save the tool
                success, message, json_path, python_path = self.rest_generator.save_tool(
                    definition, 
                    overwrite=False
                )
                
                if not success:
                    return jsonify({
                        'success': False,
                        'error': message
                    }), 400
                
                # Reload tools registry
                try:
                    self.tools_registry.reload_all_tools()
                    logger.info(f"Tools reloaded. Total tools: {len(self.tools_registry.tools)}")
                except Exception as reload_error:
                    logger.warning(f"Could not reload tools: {reload_error}")
                
                return jsonify({
                    'success': True,
                    'message': f'REST Tool "{definition.name}" deployed successfully!',
                    'json_path': json_path,
                    'python_path': python_path,
                    'tool_name': definition.name
                })
                
            except Exception as e:
                logger.error(f"Error deploying REST tool: {e}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': f'Deployment error: {str(e)}'
                }), 500
        
        # ============================================================
        # DB Query Tool Creator Routes
        # ============================================================
        
        @app.route('/admin/studio/dbquery')
        @self.admin_required
        def studio_dbquery():
            """DB Query Tool Creator page."""
            user_session = self.get_user_session()
            existing_tools = list(self.tools_registry.tools.keys())
            
            return render_template('admin/studio/studio_dbquery.html',
                                 user=user_session,
                                 existing_tools=existing_tools)
        
        @app.route('/admin/studio/dbquery/preview', methods=['POST'])
        @self.admin_required
        def studio_dbquery_preview():
            """Preview DB Query tool generation."""
            try:
                data = request.get_json()
                
                # Parse parameters
                params = []
                for p in data.get('parameters', []):
                    param = DBQueryParameter(
                        name=p.get('name', '').strip(),
                        param_type=p.get('param_type', 'string'),
                        description=p.get('description', ''),
                        required=p.get('required', True),
                        default=p.get('default') if p.get('default') else None,
                        enum=p.get('enum') if p.get('enum') else None
                    )
                    params.append(param)
                
                # Create definition from request data
                definition = DBQueryToolDefinition(
                    name=data.get('name', '').strip().lower(),
                    description=data.get('description', ''),
                    db_type=data.get('db_type', 'duckdb'),
                    connection_string=data.get('connection_string', ''),
                    query_template=data.get('query_template', ''),
                    parameters=params,
                    category=data.get('category', 'Database'),
                    tags=data.get('tags', ['database', 'query', 'sql']),
                    literature=data.get('literature', ''),
                    timeout=data.get('timeout', 30),
                    max_rows=data.get('max_rows', 1000)
                )
                
                # Check for name conflicts
                existing_tools = list(self.tools_registry.tools.keys())
                if definition.name in existing_tools:
                    return jsonify({
                        'success': False,
                        'error': f'Tool "{definition.name}" already exists'
                    }), 400
                
                # Generate preview
                preview = self.dbquery_generator.preview_tool(definition)
                
                if not preview.get('success'):
                    return jsonify({
                        'success': False,
                        'error': 'Validation errors: ' + ', '.join(preview.get('errors', []))
                    }), 400
                
                return jsonify({
                    'success': True,
                    'json_content': preview['json_content'],
                    'python_content': preview['python_content'],
                    'json_filename': preview['json_filename'],
                    'python_filename': preview['python_filename'],
                    'input_schema': preview['input_schema'],
                    'output_schema': preview['output_schema']
                })
                
            except Exception as e:
                logger.error(f"Error previewing DB Query tool: {e}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': f'Preview error: {str(e)}'
                }), 500
        
        @app.route('/admin/studio/dbquery/deploy', methods=['POST'])
        @self.admin_required
        def studio_dbquery_deploy():
            """Deploy DB Query tool."""
            try:
                data = request.get_json()
                
                # Parse parameters
                params = []
                for p in data.get('parameters', []):
                    param = DBQueryParameter(
                        name=p.get('name', '').strip(),
                        param_type=p.get('param_type', 'string'),
                        description=p.get('description', ''),
                        required=p.get('required', True),
                        default=p.get('default') if p.get('default') else None,
                        enum=p.get('enum') if p.get('enum') else None
                    )
                    params.append(param)
                
                # Create definition from request data
                definition = DBQueryToolDefinition(
                    name=data.get('name', '').strip().lower(),
                    description=data.get('description', ''),
                    db_type=data.get('db_type', 'duckdb'),
                    connection_string=data.get('connection_string', ''),
                    query_template=data.get('query_template', ''),
                    parameters=params,
                    category=data.get('category', 'Database'),
                    tags=data.get('tags', ['database', 'query', 'sql']),
                    literature=data.get('literature', ''),
                    timeout=data.get('timeout', 30),
                    max_rows=data.get('max_rows', 1000)
                )
                
                # Check for name conflicts
                existing_tools = list(self.tools_registry.tools.keys())
                if definition.name in existing_tools:
                    return jsonify({
                        'success': False,
                        'error': f'Tool "{definition.name}" already exists'
                    }), 400
                
                # Save the tool
                success, message, json_path, python_path = self.dbquery_generator.save_tool(
                    definition, 
                    overwrite=False
                )
                
                if not success:
                    return jsonify({
                        'success': False,
                        'error': message
                    }), 400
                
                # Reload tools registry
                try:
                    self.tools_registry.reload_all_tools()
                    logger.info(f"Tools reloaded. Total tools: {len(self.tools_registry.tools)}")
                except Exception as reload_error:
                    logger.warning(f"Could not reload tools: {reload_error}")
                
                return jsonify({
                    'success': True,
                    'message': f'DB Query Tool "{definition.name}" deployed successfully!',
                    'json_path': json_path,
                    'python_path': python_path,
                    'tool_name': definition.name
                })
                
            except Exception as e:
                logger.error(f"Error deploying DB Query tool: {e}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': f'Deployment error: {str(e)}'
                }), 500
        
        # ============================================================
        # Python Code Tool Creator Routes
        # ============================================================
        
        @app.route('/admin/studio/analyze', methods=['POST'])
        @self.admin_required
        def studio_analyze():
            """Analyze submitted code for @sajhamcptool decorators."""
            try:
                data = request.get_json()
                source_code = data.get('code', '')
                tool_name = data.get('tool_name', '').strip().lower()
                
                if not source_code.strip():
                    return jsonify({
                        'success': False,
                        'error': 'No code provided'
                    }), 400
                
                if not tool_name:
                    return jsonify({
                        'success': False,
                        'error': 'Tool name is required'
                    }), 400
                
                # Validate tool name
                existing_tools = list(self.tools_registry.tools.keys())
                is_valid, error_msg = self.analyzer.validate_tool_name(tool_name, existing_tools)
                if not is_valid:
                    return jsonify({
                        'success': False,
                        'error': error_msg
                    }), 400
                
                # Analyze code
                tool_defs = self.analyzer.analyze(source_code)
                
                if self.analyzer.errors:
                    return jsonify({
                        'success': False,
                        'error': 'Code analysis errors',
                        'errors': self.analyzer.errors
                    }), 400
                
                if not tool_defs:
                    return jsonify({
                        'success': False,
                        'error': 'No @sajhamcptool decorated functions found in the code. '
                                 'Make sure to use @sajhamcptool(description="...") decorator.'
                    }), 400
                
                # Use the first tool definition found
                tool_def = tool_defs[0]
                
                # Generate preview
                preview = self.generator.preview_tool(tool_def, tool_name)
                
                # Check for syntax errors in generated code
                if not preview.get('syntax_valid', True):
                    return jsonify({
                        'success': False,
                        'error': f"Generated Python has syntax error: {preview.get('syntax_error', 'Unknown error')}",
                        'python_content': preview['python'],  # Show the code so user can debug
                    }), 400
                
                return jsonify({
                    'success': True,
                    'tool_name': tool_name,
                    'function_name': tool_def.function_name,
                    'description': tool_def.description,
                    'category': tool_def.category,
                    'parameters': [
                        {
                            'name': p.name,
                            'type': p.type_hint,
                            'default': p.default_value,
                            'required': not p.has_default
                        }
                        for p in tool_def.parameters
                    ],
                    'json_content': preview['json'],
                    'python_content': preview['python'],
                    'json_filename': preview['json_filename'],
                    'python_filename': preview['python_filename'],
                    'syntax_valid': preview.get('syntax_valid', True),
                    'warnings': self.analyzer.warnings
                })
                
            except Exception as e:
                logger.error(f"Error analyzing code: {e}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': f'Analysis error: {str(e)}'
                }), 500
        
        @app.route('/admin/studio/deploy', methods=['POST'])
        @self.admin_required
        def studio_deploy():
            """Deploy the generated tool files."""
            try:
                data = request.get_json()
                source_code = data.get('code', '')
                tool_name = data.get('tool_name', '').strip().lower()
                
                if not source_code.strip() or not tool_name:
                    return jsonify({
                        'success': False,
                        'error': 'Code and tool name are required'
                    }), 400
                
                # Validate tool name again
                existing_tools = list(self.tools_registry.tools.keys())
                is_valid, error_msg = self.analyzer.validate_tool_name(tool_name, existing_tools)
                if not is_valid:
                    return jsonify({
                        'success': False,
                        'error': error_msg
                    }), 400
                
                # Analyze code
                tool_defs = self.analyzer.analyze(source_code)
                
                if not tool_defs:
                    return jsonify({
                        'success': False,
                        'error': 'No valid tool definitions found'
                    }), 400
                
                tool_def = tool_defs[0]
                
                # Save the tool (never overwrite)
                success, message, json_path, python_path = self.generator.save_tool(
                    tool_def, 
                    tool_name, 
                    overwrite=False
                )
                
                if not success:
                    return jsonify({
                        'success': False,
                        'error': message
                    }), 400
                
                # Reload tools registry to pick up the new tool
                try:
                    self.tools_registry.reload_all_tools()
                    logger.info(f"Tools reloaded. Total tools: {len(self.tools_registry.tools)}")
                except Exception as reload_error:
                    logger.warning(f"Could not reload tools: {reload_error}")
                
                return jsonify({
                    'success': True,
                    'message': f'Tool "{tool_name}" deployed successfully!',
                    'json_path': json_path,
                    'python_path': python_path,
                    'tool_name': tool_name
                })
                
            except Exception as e:
                logger.error(f"Error deploying tool: {e}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': f'Deployment error: {str(e)}'
                }), 500
        
        @app.route('/admin/studio/validate-name', methods=['POST'])
        @self.admin_required
        def studio_validate_name():
            """Validate a tool name."""
            data = request.get_json()
            tool_name = data.get('tool_name', '').strip().lower()
            
            existing_tools = list(self.tools_registry.tools.keys())
            is_valid, error_msg = self.analyzer.validate_tool_name(tool_name, existing_tools)
            
            return jsonify({
                'valid': is_valid,
                'error': error_msg if not is_valid else None
            })
        
        @app.route('/admin/studio/delete', methods=['POST'])
        @self.admin_required
        def studio_delete():
            """Delete existing tool files (JSON config and Python implementation)."""
            try:
                data = request.get_json()
                tool_name = data.get('tool_name', '').strip().lower()
                
                if not tool_name:
                    return jsonify({
                        'success': False,
                        'error': 'Tool name is required'
                    }), 400
                
                # Validate tool name format
                import re
                if not re.match(r'^[a-z][a-z0-9_]*$', tool_name) or len(tool_name) < 3:
                    return jsonify({
                        'success': False,
                        'error': 'Invalid tool name format'
                    }), 400
                
                from pathlib import Path
                
                # Determine file paths
                json_path = Path.cwd() / 'config' / 'tools' / f'{tool_name}.json'
                python_path = Path.cwd() / 'sajha' / 'tools' / 'impl' / f'studio_{tool_name}.py'
                
                deleted_files = []
                not_found_files = []
                
                # Delete JSON config if exists
                if json_path.exists():
                    json_path.unlink()
                    deleted_files.append(str(json_path))
                    logger.info(f"Deleted tool JSON: {json_path}")
                else:
                    not_found_files.append(f'{tool_name}.json')
                
                # Delete Python implementation if exists
                if python_path.exists():
                    python_path.unlink()
                    deleted_files.append(str(python_path))
                    logger.info(f"Deleted tool Python: {python_path}")
                else:
                    not_found_files.append(f'studio_{tool_name}.py')
                
                # Unregister tool from registry if it was loaded
                if tool_name in self.tools_registry.tools:
                    self.tools_registry.unregister_tool(tool_name)
                    logger.info(f"Unregistered tool: {tool_name}")
                
                # Build response message
                if deleted_files:
                    message = f'Deleted: {", ".join([f.split("/")[-1] for f in deleted_files])}'
                    if not_found_files:
                        message += f' (not found: {", ".join(not_found_files)})'
                else:
                    message = f'No files found for tool "{tool_name}"'
                
                return jsonify({
                    'success': True,
                    'message': message,
                    'deleted_files': deleted_files,
                    'not_found_files': not_found_files
                })
                
            except Exception as e:
                logger.error(f"Error deleting tool: {e}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': f'Deletion error: {str(e)}'
                }), 500
        
        # ============================================================
        # Script Tool Creator Routes
        # ============================================================
        
        @app.route('/admin/studio/script')
        @self.admin_required
        def studio_script():
            """Script Tool Creator page."""
            user_session = self.get_user_session()
            existing_tools = list(self.tools_registry.tools.keys())
            
            return render_template('admin/studio/studio_script.html',
                                 user=user_session,
                                 existing_tools=existing_tools)
        
        @app.route('/admin/studio/script/preview', methods=['POST'])
        @self.admin_required
        def studio_script_preview():
            """Preview script tool generation."""
            try:
                data = request.get_json()
                
                # Create config from request data
                config = ScriptToolConfig(
                    tool_name=data.get('tool_name', '').strip().lower(),
                    description=data.get('description', ''),
                    script_type=data.get('script_type', 'bash'),
                    script_content=data.get('script_content', ''),
                    version='2.8.0',
                    author=data.get('author', ''),
                    tags=data.get('tags', []),
                    timeout_seconds=data.get('timeout_seconds', 30),
                    working_directory=data.get('working_directory', ''),
                    environment_vars=data.get('environment_vars', {}),
                    max_args=data.get('max_args', 10),
                    arg_descriptions=data.get('arg_descriptions', []),
                    allow_stdin=data.get('allow_stdin', False),
                    capture_stderr=data.get('capture_stderr', True),
                    literature=data.get('literature', '')
                )
                
                # Check for name conflicts
                existing_tools = list(self.tools_registry.tools.keys())
                if config.tool_name in existing_tools:
                    return jsonify({
                        'success': False,
                        'error': f'Tool "{config.tool_name}" already exists'
                    }), 400
                
                # Validate configuration
                errors = self.script_generator.validate_config(config)
                if errors:
                    return jsonify({
                        'success': False,
                        'error': 'Validation errors: ' + ', '.join(errors)
                    }), 400
                
                # Generate preview
                tool_config = self.script_generator.generate_tool_config(config)
                wrapper_code = self.script_generator.generate_python_wrapper(config)
                
                return jsonify({
                    'success': True,
                    'json_content': json.dumps(tool_config, indent=2),
                    'python_content': wrapper_code,
                    'script_type': config.script_type
                })
                
            except Exception as e:
                logger.error(f"Error previewing script tool: {e}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': f'Preview error: {str(e)}'
                }), 500
        
        @app.route('/admin/studio/script/deploy', methods=['POST'])
        @self.admin_required
        def studio_script_deploy():
            """Deploy script tool."""
            try:
                data = request.get_json()
                
                # Create config from request data
                config = ScriptToolConfig(
                    tool_name=data.get('tool_name', '').strip().lower(),
                    description=data.get('description', ''),
                    script_type=data.get('script_type', 'bash'),
                    script_content=data.get('script_content', ''),
                    version='2.8.0',
                    author=data.get('author', ''),
                    tags=data.get('tags', []),
                    timeout_seconds=data.get('timeout_seconds', 30),
                    working_directory=data.get('working_directory', ''),
                    environment_vars=data.get('environment_vars', {}),
                    max_args=data.get('max_args', 10),
                    arg_descriptions=data.get('arg_descriptions', []),
                    allow_stdin=data.get('allow_stdin', False),
                    capture_stderr=data.get('capture_stderr', True),
                    literature=data.get('literature', '')
                )
                
                # Check for name conflicts
                existing_tools = list(self.tools_registry.tools.keys())
                if config.tool_name in existing_tools:
                    return jsonify({
                        'success': False,
                        'error': f'Tool "{config.tool_name}" already exists'
                    }), 400
                
                # Generate and save the tool
                result = self.script_generator.generate_tool(config)
                
                if not result.get('success'):
                    return jsonify({
                        'success': False,
                        'error': 'Errors: ' + ', '.join(result.get('errors', ['Unknown error']))
                    }), 400
                
                # Reload tools registry
                try:
                    self.tools_registry.reload_all_tools()
                    logger.info(f"Tools reloaded. Total tools: {len(self.tools_registry.tools)}")
                except Exception as reload_error:
                    logger.warning(f"Could not reload tools: {reload_error}")
                
                return jsonify({
                    'success': True,
                    'message': result.get('message', f'Script Tool "{config.tool_name}" deployed successfully!'),
                    'tool_name': config.tool_name,
                    'config_path': result.get('config_path'),
                    'script_path': result.get('script_path'),
                    'wrapper_path': result.get('wrapper_path')
                })
                
            except Exception as e:
                logger.error(f"Error deploying script tool: {e}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': f'Deployment error: {str(e)}'
                }), 500
        
        @app.route('/admin/studio/examples')
        @self.admin_required
        def studio_examples():
            """Show example code snippets."""
            user_session = self.get_user_session()
            examples = self._get_code_examples()
            return render_template('admin/studio/studio_examples.html',
                                 user=user_session,
                                 examples=examples)
        
        # ============================================
        # PowerBI Report Tool Creator Routes
        # ============================================
        
        @app.route('/admin/studio/powerbi')
        @self.admin_required
        def studio_powerbi():
            """PowerBI Report Tool Creator page."""
            user_session = self.get_user_session()
            return render_template('admin/studio/studio_powerbi.html',
                                   user=user_session)
        
        @app.route('/admin/studio/powerbi/preview', methods=['POST'])
        @self.admin_required
        def studio_powerbi_preview():
            """Preview PowerBI tool generation."""
            try:
                data = request.get_json()
                
                config = PowerBIToolConfig(
                    tool_name=data.get('tool_name', ''),
                    description=data.get('description', ''),
                    report_name=data.get('report_name', ''),
                    workspace_id=data.get('workspace_id', ''),
                    report_id=data.get('report_id', ''),
                    tenant_id=data.get('tenant_id', ''),
                    client_id=data.get('client_id', ''),
                    client_secret_env=data.get('client_secret_env', 'POWERBI_CLIENT_SECRET'),
                    version='2.8.0',
                    author=data.get('author', ''),
                    tags=data.get('tags', []),
                    page_name=data.get('page_name', ''),
                    export_format=data.get('export_format', 'PDF'),
                    timeout_seconds=data.get('timeout_seconds', 120)
                )
                
                errors = self.powerbi_generator.validate_config(config)
                if errors:
                    return jsonify({
                        'success': False,
                        'error': '; '.join(errors)
                    })
                
                tool_config = self.powerbi_generator.generate_tool_config(config)
                
                return jsonify({
                    'success': True,
                    'config': tool_config
                })
                
            except Exception as e:
                logger.error(f"Error previewing PowerBI tool: {e}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': str(e)
                })
        
        @app.route('/admin/studio/powerbi/deploy', methods=['POST'])
        @self.admin_required
        def studio_powerbi_deploy():
            """Deploy PowerBI tool."""
            try:
                data = request.get_json()
                
                config = PowerBIToolConfig(
                    tool_name=data.get('tool_name', ''),
                    description=data.get('description', ''),
                    report_name=data.get('report_name', ''),
                    workspace_id=data.get('workspace_id', ''),
                    report_id=data.get('report_id', ''),
                    tenant_id=data.get('tenant_id', ''),
                    client_id=data.get('client_id', ''),
                    client_secret_env=data.get('client_secret_env', 'POWERBI_CLIENT_SECRET'),
                    version='2.8.0',
                    author=data.get('author', ''),
                    tags=data.get('tags', []),
                    page_name=data.get('page_name', ''),
                    export_format=data.get('export_format', 'PDF'),
                    timeout_seconds=data.get('timeout_seconds', 120)
                )
                
                result = self.powerbi_generator.generate_tool(config)
                
                if result['success']:
                    return jsonify({
                        'success': True,
                        'message': result['message'],
                        'files': result['files'],
                        'config': self.powerbi_generator.generate_tool_config(config)
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': result['message']
                    })
                
            except Exception as e:
                logger.error(f"Error deploying PowerBI tool: {e}", exc_info=True)
                return jsonify({
                    'success': False,
                    'error': str(e)
                })
        
        # ============================================
        # PowerBI DAX Query Tool Creator Routes
        # ============================================
        
        @app.route('/admin/studio/powerbidax')
        @self.admin_required
        def studio_powerbidax():
            """PowerBI DAX Query Tool Creator page."""
            user_session = self.get_user_session()
            return render_template('admin/studio/studio_powerbidax.html',
                                   user=user_session)
        
        @app.route('/admin/studio/powerbidax/preview', methods=['POST'])
        @self.admin_required
        def studio_powerbidax_preview():
            """Preview PowerBI DAX tool generation."""
            try:
                data = request.get_json()
                
                config = PowerBIDAXToolConfig(
                    tool_name=data.get('tool_name', ''),
                    description=data.get('description', ''),
                    dataset_name=data.get('dataset_name', ''),
                    workspace_id=data.get('workspace_id', ''),
                    dataset_id=data.get('dataset_id', ''),
                    dax_query=data.get('dax_query', ''),
                    tenant_id=data.get('tenant_id', ''),
                    client_id=data.get('client_id', ''),
                    client_secret_env=data.get('client_secret_env', 'POWERBI_CLIENT_SECRET'),
                    version='2.8.0',
                    author=data.get('author', ''),
                    tags=data.get('tags', []),
                    timeout_seconds=data.get('timeout_seconds', 60),
                    max_rows=data.get('max_rows', 10000),
                    parameters=data.get('parameters', [])
                )
                
                errors = self.powerbidax_generator.validate_config(config)
                if errors:
                    return jsonify({'success': False, 'error': '; '.join(errors)})
                
                tool_config = self.powerbidax_generator.generate_tool_config(config)
                return jsonify({'success': True, 'config': tool_config})
                
            except Exception as e:
                logger.error(f"Error previewing PowerBI DAX tool: {e}", exc_info=True)
                return jsonify({'success': False, 'error': str(e)})
        
        @app.route('/admin/studio/powerbidax/deploy', methods=['POST'])
        @self.admin_required
        def studio_powerbidax_deploy():
            """Deploy PowerBI DAX tool."""
            try:
                data = request.get_json()
                
                config = PowerBIDAXToolConfig(
                    tool_name=data.get('tool_name', ''),
                    description=data.get('description', ''),
                    dataset_name=data.get('dataset_name', ''),
                    workspace_id=data.get('workspace_id', ''),
                    dataset_id=data.get('dataset_id', ''),
                    dax_query=data.get('dax_query', ''),
                    tenant_id=data.get('tenant_id', ''),
                    client_id=data.get('client_id', ''),
                    client_secret_env=data.get('client_secret_env', 'POWERBI_CLIENT_SECRET'),
                    version='2.8.0',
                    author=data.get('author', ''),
                    tags=data.get('tags', []),
                    timeout_seconds=data.get('timeout_seconds', 60),
                    max_rows=data.get('max_rows', 10000),
                    parameters=data.get('parameters', [])
                )
                
                result = self.powerbidax_generator.generate_tool(config)
                
                if result['success']:
                    return jsonify({
                        'success': True,
                        'message': result['message'],
                        'files': result['files'],
                        'config': self.powerbidax_generator.generate_tool_config(config)
                    })
                else:
                    return jsonify({'success': False, 'error': result['message']})
                
            except Exception as e:
                logger.error(f"Error deploying PowerBI DAX tool: {e}", exc_info=True)
                return jsonify({'success': False, 'error': str(e)})
        
        # ============================================
        # IBM LiveLink Document Tool Creator Routes
        # ============================================
        
        @app.route('/admin/studio/livelink')
        @self.admin_required
        def studio_livelink():
            """IBM LiveLink Document Tool Creator page."""
            user_session = self.get_user_session()
            return render_template('admin/studio/studio_livelink.html',
                                   user=user_session)
        
        @app.route('/admin/studio/livelink/preview', methods=['POST'])
        @self.admin_required
        def studio_livelink_preview():
            """Preview LiveLink tool generation."""
            try:
                data = request.get_json()
                
                config = LiveLinkToolConfig(
                    tool_name=data.get('tool_name', ''),
                    description=data.get('description', ''),
                    server_url=data.get('server_url', ''),
                    auth_type=data.get('auth_type', 'basic'),
                    username_env=data.get('username_env', 'LIVELINK_USERNAME'),
                    password_env=data.get('password_env', 'LIVELINK_PASSWORD'),
                    oauth_token_env=data.get('oauth_token_env', 'LIVELINK_OAUTH_TOKEN'),
                    default_parent_id=data.get('default_parent_id', ''),
                    document_types=data.get('document_types', []),
                    version='2.8.0',
                    author=data.get('author', ''),
                    tags=data.get('tags', []),
                    timeout_seconds=data.get('timeout_seconds', 60),
                    max_file_size_mb=data.get('max_file_size_mb', 50),
                    api_version=data.get('api_version', 'v2')
                )
                
                errors = self.livelink_generator.validate_config(config)
                if errors:
                    return jsonify({'success': False, 'error': '; '.join(errors)})
                
                tool_config = self.livelink_generator.generate_tool_config(config)
                return jsonify({'success': True, 'config': tool_config})
                
            except Exception as e:
                logger.error(f"Error previewing LiveLink tool: {e}", exc_info=True)
                return jsonify({'success': False, 'error': str(e)})
        
        @app.route('/admin/studio/livelink/deploy', methods=['POST'])
        @self.admin_required
        def studio_livelink_deploy():
            """Deploy LiveLink tool."""
            try:
                data = request.get_json()
                
                config = LiveLinkToolConfig(
                    tool_name=data.get('tool_name', ''),
                    description=data.get('description', ''),
                    server_url=data.get('server_url', ''),
                    auth_type=data.get('auth_type', 'basic'),
                    username_env=data.get('username_env', 'LIVELINK_USERNAME'),
                    password_env=data.get('password_env', 'LIVELINK_PASSWORD'),
                    oauth_token_env=data.get('oauth_token_env', 'LIVELINK_OAUTH_TOKEN'),
                    default_parent_id=data.get('default_parent_id', ''),
                    document_types=data.get('document_types', []),
                    version='2.8.0',
                    author=data.get('author', ''),
                    tags=data.get('tags', []),
                    timeout_seconds=data.get('timeout_seconds', 60),
                    max_file_size_mb=data.get('max_file_size_mb', 50),
                    api_version=data.get('api_version', 'v2')
                )
                
                result = self.livelink_generator.generate_tool(config)
                
                if result['success']:
                    return jsonify({
                        'success': True,
                        'message': result['message'],
                        'files': result['files'],
                        'config': self.livelink_generator.generate_tool_config(config)
                    })
                else:
                    return jsonify({'success': False, 'error': result['message']})
                
            except Exception as e:
                logger.error(f"Error deploying LiveLink tool: {e}", exc_info=True)
                return jsonify({'success': False, 'error': str(e)})
        
        # ========== OLAP Dataset Creator Routes ==========
        
        @app.route('/admin/studio/olap')
        @self.admin_required
        def studio_olap():
            """OLAP Dataset Creator page."""
            user_session = self.get_user_session()
            existing_tools = list(self.tools_registry.tools.keys())
            return render_template('admin/studio/studio_olap.html', 
                                 user=user_session,
                                 existing_tools=existing_tools)
        
        @app.route('/admin/studio/olap/deploy', methods=['POST'])
        @self.admin_required
        def studio_olap_deploy():
            """Deploy OLAP dataset configuration."""
            try:
                data = request.get_json()
                
                # Validate required fields
                if not data.get('name'):
                    return jsonify({'success': False, 'error': 'Dataset name is required'})
                if not data.get('source_table'):
                    return jsonify({'success': False, 'error': 'Source table is required'})
                if not data.get('dimensions'):
                    return jsonify({'success': False, 'error': 'At least one dimension is required'})
                if not data.get('measures'):
                    return jsonify({'success': False, 'error': 'At least one measure is required'})
                
                # Load existing datasets config
                import json
                from pathlib import Path
                
                config_path = Path(__file__).parent.parent.parent.parent / 'config' / 'olap' / 'datasets.json'
                
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                else:
                    config = {
                        'version': '2.8.0',
                        'description': 'OLAP Dataset Definitions for Semantic Layer',
                        'datasets': {}
                    }
                
                # Add new dataset
                dataset_name = data['name']
                config['datasets'][dataset_name] = {
                    'name': data.get('display_name', dataset_name),
                    'description': data.get('description', ''),
                    'source_table': data['source_table'],
                    'joins': data.get('joins', []),
                    'dimensions': data['dimensions'],
                    'measures': data['measures'],
                    'default_time_dimension': data.get('default_time_dimension'),
                    'default_grain': data.get('default_grain', 'month'),
                    'cache_ttl_seconds': 300,
                    'tags': []
                }
                
                # Save config
                config_path.parent.mkdir(parents=True, exist_ok=True)
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=4)
                
                return jsonify({
                    'success': True,
                    'message': f'Dataset "{dataset_name}" deployed successfully!',
                    'dataset': dataset_name
                })
                
            except Exception as e:
                logger.error(f"Error deploying OLAP dataset: {e}", exc_info=True)
                return jsonify({'success': False, 'error': str(e)})
    
    def _get_sample_code(self) -> str:
        """Get sample code for the studio editor."""
        return '''from sajha.studio import sajhamcptool

@sajhamcptool(
    description="Calculate the factorial of a number",
    category="Mathematics",
    tags=["math", "factorial", "calculation"]
)
def calculate_factorial(n: int) -> dict:
    """Calculate factorial of n."""
    if n < 0:
        return {"error": "Factorial not defined for negative numbers"}
    
    result = 1
    for i in range(1, n + 1):
        result *= i
    
    return {
        "input": n,
        "factorial": result
    }
'''
    
    def _get_code_examples(self) -> list:
        """Get list of code examples."""
        return [
            {
                'title': 'Simple Calculator',
                'description': 'Basic arithmetic calculator tool',
                'code': '''@sajhamcptool(
    description="Perform basic arithmetic operations",
    category="Mathematics",
    tags=["calculator", "math"]
)
def simple_calculator(
    a: float, 
    b: float, 
    operation: str = "add"
) -> dict:
    """Perform arithmetic operation on two numbers."""
    operations = {
        "add": a + b,
        "subtract": a - b,
        "multiply": a * b,
        "divide": a / b if b != 0 else None
    }
    
    result = operations.get(operation)
    if result is None:
        return {"error": f"Invalid operation: {operation}"}
    
    return {
        "a": a,
        "b": b,
        "operation": operation,
        "result": result
    }
'''
            },
            {
                'title': 'Text Analyzer',
                'description': 'Analyze text and return statistics',
                'code': '''@sajhamcptool(
    description="Analyze text and return word/character statistics",
    category="Text Processing",
    tags=["text", "analysis", "nlp"]
)
def analyze_text(
    text: str, 
    include_details: bool = False
) -> dict:
    """Analyze text content."""
    words = text.split()
    
    result = {
        "character_count": len(text),
        "word_count": len(words),
        "sentence_count": text.count('.') + text.count('!') + text.count('?'),
        "average_word_length": sum(len(w) for w in words) / len(words) if words else 0
    }
    
    if include_details:
        result["word_frequency"] = {}
        for word in words:
            word_lower = word.lower().strip('.,!?')
            result["word_frequency"][word_lower] = result["word_frequency"].get(word_lower, 0) + 1
    
    return result
'''
            },
            {
                'title': 'Data Formatter',
                'description': 'Format data in different output formats',
                'code': '''@sajhamcptool(
    description="Format structured data into various output formats",
    category="Data Processing",
    tags=["format", "json", "csv"]
)
def format_data(
    data: dict,
    output_format: str = "json",
    pretty: bool = True
) -> dict:
    """Format data into specified output format."""
    import json
    
    if output_format == "json":
        formatted = json.dumps(data, indent=2 if pretty else None)
    elif output_format == "csv":
        if isinstance(data, dict):
            headers = ','.join(str(k) for k in data.keys())
            values = ','.join(str(v) for v in data.values())
            formatted = f"{headers}\\n{values}"
        else:
            formatted = str(data)
    else:
        formatted = str(data)
    
    return {
        "original": data,
        "format": output_format,
        "formatted": formatted
    }
'''
            }
        ]
