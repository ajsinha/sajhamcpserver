"""
SAJHA MCP Server - MCP Studio Routes v2.2.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Routes for the MCP Studio feature - admin-only tool creation interface.
"""

import json
import logging
from flask import request, render_template, jsonify, flash, redirect, url_for
from .base_routes import BaseRoutes

from sajha.studio import CodeAnalyzer, ToolCodeGenerator, ToolDefinition

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
    
    def register_routes(self, app):
        """Register MCP Studio routes."""
        
        @app.route('/admin/studio')
        @self.admin_required
        def studio_home():
            """MCP Studio main page."""
            # Get list of existing tools for conflict detection
            existing_tools = list(self.tools_registry.tools.keys())
            
            return render_template('admin/studio/studio_home.html',
                                 existing_tools=existing_tools,
                                 sample_code=self._get_sample_code())
        
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
        
        @app.route('/admin/studio/examples')
        @self.admin_required
        def studio_examples():
            """Show example code snippets."""
            examples = self._get_code_examples()
            return render_template('admin/studio/studio_examples.html',
                                 examples=examples)
    
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
