"""
SAJHA MCP Server - Tool Code Generator v2.3.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Generates MCP tool JSON configuration and Python implementation files
from ToolDefinition objects extracted by CodeAnalyzer.
"""

import json
import re
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Tuple
from .code_analyzer import ToolDefinition

logger = logging.getLogger(__name__)


class ToolCodeGenerator:
    """
    Generates MCP tool files (JSON config and Python implementation)
    from ToolDefinition objects.
    """
    
    VERSION = '2.9.6'
    
    def __init__(
        self, 
        tools_dir: str = 'config/tools',
        impl_dir: str = 'sajha/tools/impl'
    ):
        """
        Initialize the code generator.
        
        Args:
            tools_dir: Directory for tool JSON configs
            impl_dir: Directory for Python implementations
        """
        self.tools_dir = Path(tools_dir)
        self.impl_dir = Path(impl_dir)
        
        # Make paths absolute if relative
        if not self.tools_dir.is_absolute():
            self.tools_dir = Path.cwd() / self.tools_dir
        if not self.impl_dir.is_absolute():
            self.impl_dir = Path.cwd() / self.impl_dir
    
    def generate_tool_json(
        self, 
        tool_def: ToolDefinition, 
        tool_name: str
    ) -> str:
        """
        Generate JSON configuration for the tool.
        
        Args:
            tool_def: Tool definition from code analysis
            tool_name: Name for the tool
            
        Returns:
            JSON string of the tool configuration
        """
        # Convert tool name to class name
        class_name = self._to_class_name(tool_name)
        
        # Create module name from tool name
        module_name = f"studio_{tool_name}"
        
        config = {
            "name": tool_name,
            "implementation": f"sajha.tools.impl.{module_name}.{class_name}Tool",
            "description": tool_def.description,
            "version": self.VERSION,
            "enabled": tool_def.enabled,
            "metadata": {
                "author": tool_def.author,
                "category": tool_def.category,
                "tags": tool_def.tags + ["mcp-studio", "generated"],
                "rateLimit": tool_def.rate_limit,
                "cacheTTL": tool_def.cache_ttl,
                "createdAt": datetime.now().isoformat(),
                "source": "MCP Studio"
            }
        }
        
        return json.dumps(config, indent=2)
    
    def generate_python_code(
        self, 
        tool_def: ToolDefinition, 
        tool_name: str
    ) -> str:
        """
        Generate Python implementation file for the tool.
        
        Args:
            tool_def: Tool definition from code analysis
            tool_name: Name for the tool
            
        Returns:
            Python source code string
        """
        class_name = self._to_class_name(tool_name)
        module_name = f"studio_{tool_name}"
        
        # Build input schema
        input_schema = tool_def.get_input_schema()
        
        # Build output schema
        output_schema = tool_def.get_output_schema()
        
        # Extract the function body (remove decorators and def line)
        func_body = self._extract_function_body(tool_def.source_code)
        
        # Escape description for use in string
        escaped_description = tool_def.description.replace("'", "\\'").replace('"', '\\"')
        
        # Format schemas as Python code
        input_schema_str = self._format_schema(input_schema)
        output_schema_str = self._format_schema(output_schema)
        
        # Generate argument extraction code
        arg_extraction_lines = ['# Extract arguments']
        for param in tool_def.parameters:
            if param.has_default:
                if param.default_value is None:
                    arg_extraction_lines.append(f"{param.name} = arguments.get('{param.name}')")
                elif isinstance(param.default_value, str):
                    arg_extraction_lines.append(f"{param.name} = arguments.get('{param.name}', '{param.default_value}')")
                else:
                    arg_extraction_lines.append(f"{param.name} = arguments.get('{param.name}', {param.default_value})")
            else:
                arg_extraction_lines.append(f"{param.name} = arguments['{param.name}']")
        arg_extraction_lines.append('')  # Empty line after extractions
        
        arg_extraction = '\n'.join(arg_extraction_lines)
        
        # Combine argument extraction with function body
        full_body = arg_extraction + '\n' + func_body
        
        # Indent the full body
        indented_body = self._indent_code(full_body, 8)
        
        # Build the Python code using string concatenation to avoid f-string issues
        code_parts = [
            '"""',
            f'SAJHA MCP Server - {tool_name} Tool v{self.VERSION}',
            '',
            'Copyright © 2025-2030, All Rights Reserved',
            'Generated by MCP Studio',
            '',
            f'Description: {tool_def.description}',
            f'Category: {tool_def.category}',
            f'Author: {tool_def.author}',
            '"""',
            '',
            'from typing import Dict, Any, List, Optional',
            'from sajha.tools.base_mcp_tool import BaseMCPTool',
            '',
            '',
            f'class {class_name}Tool(BaseMCPTool):',
            '    """',
            f'    {tool_def.description}',
            '    ',
            '    Generated by MCP Studio from @sajhamcptool decorated function.',
            '    """',
            '    ',
            '    def __init__(self, config: Dict = None):',
            f'        """Initialize {tool_name} tool."""',
            '        default_config = {',
            f"            'name': '{tool_name}',",
            f"            'description': '{escaped_description}',",
            f"            'version': '{self.VERSION}',",
            f"            'enabled': {tool_def.enabled}",
            '        }',
            '        if config:',
            '            default_config.update(config)',
            '        super().__init__(default_config)',
            '    ',
            '    def get_input_schema(self) -> Dict:',
            '        """Define the input schema for this tool."""',
            f'        return {input_schema_str}',
            '    ',
            '    def get_output_schema(self) -> Dict:',
            '        """Define the output schema for this tool."""',
            f'        return {output_schema_str}',
            '    ',
            '    def execute(self, arguments: Dict[str, Any]) -> Dict:',
            '        """',
            '        Execute the tool with provided arguments.',
            '        ',
            '        Args:',
            '            arguments: Dictionary of input arguments',
            '            ',
            '        Returns:',
            '            Tool execution result',
            '        """',
            indented_body,
            '',
            '',
            '# Tool registry entry',
            f'{tool_name.upper()}_TOOLS = {{',
            f"    '{tool_name}': {class_name}Tool",
            '}',
        ]
        
        return '\n'.join(code_parts)
    
    def _extract_function_body(self, source_code: str) -> str:
        """Extract just the function body from source code."""
        lines = source_code.split('\n')
        body_lines = []
        in_body = False
        in_docstring = False
        base_indent = None
        
        for line in lines:
            stripped = line.strip()
            
            # Skip empty lines at the start
            if not stripped and not in_body and not in_docstring:
                continue
            
            # Skip decorator and def line
            if stripped.startswith('@') or stripped.startswith('def '):
                continue
            
            # Handle docstrings
            if not in_body and not in_docstring:
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    quote = '"""' if stripped.startswith('"""') else "'''"
                    if stripped.count(quote) >= 2:
                        # Single line docstring
                        continue
                    else:
                        # Multi-line docstring start
                        in_docstring = True
                        continue
            
            if in_docstring:
                if '"""' in stripped or "'''" in stripped:
                    in_docstring = False
                continue
            
            in_body = True
            
            # Track base indentation from first non-empty line
            if base_indent is None and stripped:
                base_indent = len(line) - len(line.lstrip())
            
            body_lines.append(line)
        
        if not body_lines:
            # Default implementation if body is empty
            return "# Extract arguments from 'arguments' dict\n# Add implementation here\nreturn arguments"
        
        # Remove base indentation to normalize the code
        if base_indent and base_indent > 0:
            normalized_lines = []
            for line in body_lines:
                if line.strip():
                    # Remove base indentation, keep relative indentation
                    if len(line) >= base_indent and line[:base_indent].strip() == '':
                        normalized_lines.append(line[base_indent:])
                    else:
                        normalized_lines.append(line.lstrip())
                else:
                    normalized_lines.append('')
            body_lines = normalized_lines
        
        result = '\n'.join(body_lines)
        
        # If the body doesn't return anything, add a default return
        if 'return' not in result:
            result += '\nreturn {"status": "success"}'
        
        return result
    
    def _indent_code(self, code: str, spaces: int) -> str:
        """
        Indent code by specified number of spaces while preserving relative indentation.
        
        Args:
            code: Source code string (normalized with no base indentation)
            spaces: Number of spaces to add to each line
        """
        lines = code.split('\n')
        indented = []
        indent_str = ' ' * spaces
        
        for line in lines:
            if line.strip():
                # Add base indentation while preserving existing relative indentation
                indented.append(indent_str + line)
            else:
                indented.append('')
        
        return '\n'.join(indented)
    
    def _format_schema(self, schema: Dict) -> str:
        """Format a schema dictionary as Python code."""
        return json.dumps(schema, indent=8).replace('true', 'True').replace('false', 'False').replace('null', 'None')
    
    def _to_class_name(self, tool_name: str) -> str:
        """Convert tool_name to ClassName format."""
        # Split by underscore and capitalize each part
        parts = tool_name.split('_')
        return ''.join(part.capitalize() for part in parts)
    
    def save_tool(
        self, 
        tool_def: ToolDefinition, 
        tool_name: str,
        overwrite: bool = False
    ) -> Tuple[bool, str, Optional[str], Optional[str]]:
        """
        Save generated tool files to disk.
        
        Args:
            tool_def: Tool definition
            tool_name: Tool name
            overwrite: Allow overwriting existing files
            
        Returns:
            Tuple of (success, message, json_path, python_path)
        """
        import ast
        
        module_name = f"studio_{tool_name}"
        
        json_path = self.tools_dir / f"{tool_name}.json"
        python_path = self.impl_dir / f"{module_name}.py"
        
        # Check for existing files
        if not overwrite:
            if json_path.exists():
                return False, f"JSON config already exists: {json_path}", None, None
            if python_path.exists():
                return False, f"Python file already exists: {python_path}", None, None
        
        try:
            # Ensure directories exist
            self.tools_dir.mkdir(parents=True, exist_ok=True)
            self.impl_dir.mkdir(parents=True, exist_ok=True)
            
            # Generate files
            json_content = self.generate_tool_json(tool_def, tool_name)
            python_content = self.generate_python_code(tool_def, tool_name)
            
            # Validate Python syntax before saving
            try:
                ast.parse(python_content)
            except SyntaxError as e:
                logger.error(f"Generated Python has syntax error: {e}")
                return False, f"Generated Python has syntax error on line {e.lineno}: {e.msg}", None, None
            
            # Save JSON config
            with open(json_path, 'w', encoding='utf-8') as f:
                f.write(json_content)
            logger.info(f"Saved tool JSON: {json_path}")
            
            # Save Python implementation
            with open(python_path, 'w', encoding='utf-8') as f:
                f.write(python_content)
            logger.info(f"Saved tool Python: {python_path}")
            
            return True, "Tool saved successfully", str(json_path), str(python_path)
            
        except Exception as e:
            logger.error(f"Error saving tool: {e}")
            return False, f"Error saving tool: {str(e)}", None, None
    
    def preview_tool(
        self, 
        tool_def: ToolDefinition, 
        tool_name: str
    ) -> Dict[str, Any]:
        """
        Generate preview of tool files without saving.
        
        Args:
            tool_def: Tool definition
            tool_name: Tool name
            
        Returns:
            Dictionary with 'json', 'python', filenames, and validation results
        """
        import ast
        
        python_content = self.generate_python_code(tool_def, tool_name)
        
        # Validate Python syntax
        syntax_valid = True
        syntax_error = None
        try:
            ast.parse(python_content)
        except SyntaxError as e:
            syntax_valid = False
            syntax_error = f"Line {e.lineno}: {e.msg}"
        
        return {
            'json': self.generate_tool_json(tool_def, tool_name),
            'python': python_content,
            'json_filename': f"{tool_name}.json",
            'python_filename': f"studio_{tool_name}.py",
            'syntax_valid': syntax_valid,
            'syntax_error': syntax_error
        }
