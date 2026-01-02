"""
SAJHA MCP Server - Code Analyzer v2.2.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Analyzes Python code to extract @sajhamcptool decorated functions
and their metadata for MCP tool generation.
"""

import ast
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ParameterInfo:
    """Information about a function parameter."""
    name: str
    type_hint: str = "any"
    default_value: Any = None
    has_default: bool = False
    description: str = ""
    
    def to_json_schema(self) -> Dict[str, Any]:
        """Convert to JSON Schema property definition."""
        type_mapping = {
            'str': 'string',
            'string': 'string',
            'int': 'integer',
            'integer': 'integer',
            'float': 'number',
            'number': 'number',
            'bool': 'boolean',
            'boolean': 'boolean',
            'list': 'array',
            'List': 'array',
            'dict': 'object',
            'Dict': 'object',
            'any': 'string',
            'Any': 'string',
            'Optional': 'string',
            'None': 'null'
        }
        
        # Handle Optional[X] and List[X] type hints
        base_type = self.type_hint
        if '[' in base_type:
            base_type = base_type.split('[')[0]
        
        json_type = type_mapping.get(base_type, 'string')
        
        schema = {"type": json_type}
        
        if self.description:
            schema["description"] = self.description
        
        if self.has_default and self.default_value is not None:
            schema["default"] = self.default_value
        
        return schema


@dataclass
class ToolDefinition:
    """Complete tool definition extracted from code."""
    function_name: str
    description: str
    parameters: List[ParameterInfo] = field(default_factory=list)
    return_type: str = "dict"
    category: str = "General"
    tags: List[str] = field(default_factory=list)
    author: str = "MCP Studio User"
    version: str = "1.0.0"
    rate_limit: int = 60
    cache_ttl: int = 300
    enabled: bool = True
    docstring: str = ""
    source_code: str = ""
    
    def get_input_schema(self) -> Dict[str, Any]:
        """Generate JSON Schema for input parameters."""
        properties = {}
        required = []
        
        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if not param.has_default:
                required.append(param.name)
        
        schema = {
            "type": "object",
            "properties": properties
        }
        
        if required:
            schema["required"] = required
        
        return schema
    
    def get_output_schema(self) -> Dict[str, Any]:
        """Generate JSON Schema for output."""
        type_mapping = {
            'dict': 'object',
            'Dict': 'object',
            'list': 'array',
            'List': 'array',
            'str': 'string',
            'int': 'integer',
            'float': 'number',
            'bool': 'boolean'
        }
        
        base_type = self.return_type
        if '[' in base_type:
            base_type = base_type.split('[')[0]
        
        return {
            "type": type_mapping.get(base_type, "object"),
            "description": f"Result from {self.function_name}"
        }


class CodeAnalyzer:
    """
    Analyzes Python code to extract @sajhamcptool decorated functions.
    Uses AST parsing for accurate extraction of function signatures.
    """
    
    DECORATOR_NAME = 'sajhamcptool'
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def analyze(self, source_code: str) -> List[ToolDefinition]:
        """
        Analyze source code and extract all @sajhamcptool decorated functions.
        
        Args:
            source_code: Python source code string
            
        Returns:
            List of ToolDefinition objects
        """
        self.errors = []
        self.warnings = []
        
        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            self.errors.append(f"Syntax error in code: {e}")
            return []
        
        tools = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                tool_def = self._extract_tool_definition(node, source_code)
                if tool_def:
                    tools.append(tool_def)
        
        return tools
    
    def _extract_tool_definition(
        self, 
        func_node: ast.FunctionDef, 
        source_code: str
    ) -> Optional[ToolDefinition]:
        """Extract tool definition from a function node."""
        
        # Check for @sajhamcptool decorator
        decorator_info = self._get_sajhamcptool_decorator(func_node)
        if not decorator_info:
            return None
        
        # Extract function name
        function_name = func_node.name
        
        # Extract description from decorator
        description = decorator_info.get('description', f"Tool: {function_name}")
        
        # Extract other decorator arguments
        category = decorator_info.get('category', 'General')
        tags = decorator_info.get('tags', [])
        author = decorator_info.get('author', 'MCP Studio User')
        version = decorator_info.get('version', '1.0.0')
        rate_limit = decorator_info.get('rate_limit', 60)
        cache_ttl = decorator_info.get('cache_ttl', 300)
        enabled = decorator_info.get('enabled', True)
        
        # Extract parameters
        parameters = self._extract_parameters(func_node)
        
        # Extract return type
        return_type = self._extract_return_type(func_node)
        
        # Extract docstring
        docstring = ast.get_docstring(func_node) or ""
        
        # Extract source code of the function
        func_source = self._extract_function_source(func_node, source_code)
        
        return ToolDefinition(
            function_name=function_name,
            description=description,
            parameters=parameters,
            return_type=return_type,
            category=category,
            tags=tags,
            author=author,
            version=version,
            rate_limit=rate_limit,
            cache_ttl=cache_ttl,
            enabled=enabled,
            docstring=docstring,
            source_code=func_source
        )
    
    def _get_sajhamcptool_decorator(self, func_node: ast.FunctionDef) -> Optional[Dict]:
        """Find and parse @sajhamcptool decorator."""
        for decorator in func_node.decorator_list:
            if isinstance(decorator, ast.Call):
                # @sajhamcptool(...)
                if isinstance(decorator.func, ast.Name):
                    if decorator.func.id == self.DECORATOR_NAME:
                        return self._parse_decorator_args(decorator)
            elif isinstance(decorator, ast.Name):
                # @sajhamcptool (without parentheses - invalid usage)
                if decorator.id == self.DECORATOR_NAME:
                    self.warnings.append(
                        f"@{self.DECORATOR_NAME} requires description parameter"
                    )
        return None
    
    def _parse_decorator_args(self, decorator: ast.Call) -> Dict[str, Any]:
        """Parse arguments from decorator call."""
        args = {}
        
        # Parse keyword arguments
        for keyword in decorator.keywords:
            key = keyword.arg
            value = self._eval_ast_value(keyword.value)
            if key and value is not None:
                args[key] = value
        
        # Parse positional arguments (first one is description)
        if decorator.args:
            first_arg = self._eval_ast_value(decorator.args[0])
            if first_arg:
                args['description'] = first_arg
        
        return args
    
    def _eval_ast_value(self, node: ast.AST) -> Any:
        """Safely evaluate AST node to Python value."""
        try:
            if isinstance(node, ast.Constant):
                return node.value
            elif isinstance(node, ast.Str):  # Python 3.7 compatibility
                return node.s
            elif isinstance(node, ast.Num):  # Python 3.7 compatibility
                return node.n
            elif isinstance(node, ast.List):
                return [self._eval_ast_value(elt) for elt in node.elts]
            elif isinstance(node, ast.Tuple):
                return tuple(self._eval_ast_value(elt) for elt in node.elts)
            elif isinstance(node, ast.Dict):
                return {
                    self._eval_ast_value(k): self._eval_ast_value(v)
                    for k, v in zip(node.keys, node.values)
                }
            elif isinstance(node, ast.NameConstant):  # Python 3.7 compatibility
                return node.value
            elif isinstance(node, ast.Name):
                # Handle True, False, None
                if node.id == 'True':
                    return True
                elif node.id == 'False':
                    return False
                elif node.id == 'None':
                    return None
                return node.id
        except Exception as e:
            logger.warning(f"Could not evaluate AST node: {e}")
        return None
    
    def _extract_parameters(self, func_node: ast.FunctionDef) -> List[ParameterInfo]:
        """Extract parameter information from function signature."""
        parameters = []
        args = func_node.args
        
        # Get default values (aligned from the right)
        defaults = args.defaults
        num_defaults = len(defaults)
        num_args = len(args.args)
        
        for i, arg in enumerate(args.args):
            # Skip 'self' parameter
            if arg.arg == 'self':
                continue
            
            param_name = arg.arg
            
            # Extract type hint
            type_hint = 'any'
            if arg.annotation:
                type_hint = self._get_type_hint_str(arg.annotation)
            
            # Check for default value
            has_default = False
            default_value = None
            default_index = i - (num_args - num_defaults)
            if default_index >= 0 and default_index < num_defaults:
                has_default = True
                default_value = self._eval_ast_value(defaults[default_index])
            
            parameters.append(ParameterInfo(
                name=param_name,
                type_hint=type_hint,
                default_value=default_value,
                has_default=has_default
            ))
        
        # Handle keyword-only args
        for i, arg in enumerate(args.kwonlyargs):
            param_name = arg.arg
            type_hint = 'any'
            if arg.annotation:
                type_hint = self._get_type_hint_str(arg.annotation)
            
            has_default = False
            default_value = None
            if i < len(args.kw_defaults) and args.kw_defaults[i] is not None:
                has_default = True
                default_value = self._eval_ast_value(args.kw_defaults[i])
            
            parameters.append(ParameterInfo(
                name=param_name,
                type_hint=type_hint,
                default_value=default_value,
                has_default=has_default
            ))
        
        return parameters
    
    def _get_type_hint_str(self, annotation: ast.AST) -> str:
        """Convert type annotation AST to string."""
        try:
            if isinstance(annotation, ast.Name):
                return annotation.id
            elif isinstance(annotation, ast.Constant):
                return str(annotation.value)
            elif isinstance(annotation, ast.Subscript):
                # Handle List[str], Dict[str, int], Optional[str], etc.
                base = self._get_type_hint_str(annotation.value)
                if isinstance(annotation.slice, ast.Index):  # Python 3.8
                    inner = self._get_type_hint_str(annotation.slice.value)
                else:
                    inner = self._get_type_hint_str(annotation.slice)
                return f"{base}[{inner}]"
            elif isinstance(annotation, ast.Tuple):
                types = [self._get_type_hint_str(elt) for elt in annotation.elts]
                return ', '.join(types)
            elif isinstance(annotation, ast.Attribute):
                # Handle typing.Dict, etc.
                return annotation.attr
        except Exception as e:
            logger.warning(f"Could not parse type hint: {e}")
        return 'any'
    
    def _extract_return_type(self, func_node: ast.FunctionDef) -> str:
        """Extract return type from function."""
        if func_node.returns:
            return self._get_type_hint_str(func_node.returns)
        return 'dict'
    
    def _extract_function_source(
        self, 
        func_node: ast.FunctionDef, 
        source_code: str
    ) -> str:
        """Extract the source code of the function (without decorator)."""
        lines = source_code.split('\n')
        
        # Find function start (after decorators)
        func_start = func_node.lineno - 1
        
        # Find function end
        func_end = func_node.end_lineno if hasattr(func_node, 'end_lineno') else len(lines)
        
        # Get function body lines (skip decorator lines)
        func_lines = []
        in_function = False
        for i in range(func_start, func_end):
            line = lines[i] if i < len(lines) else ''
            stripped = line.strip()
            
            # Skip decorator lines
            if stripped.startswith('@') and not in_function:
                continue
            
            if stripped.startswith('def '):
                in_function = True
            
            if in_function:
                func_lines.append(line)
        
        return '\n'.join(func_lines)
    
    def validate_tool_name(
        self, 
        tool_name: str, 
        existing_tools: List[str]
    ) -> Tuple[bool, str]:
        """
        Validate that a tool name is valid and doesn't conflict.
        
        Args:
            tool_name: Proposed tool name
            existing_tools: List of existing tool names
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        # Check format
        if not re.match(r'^[a-z][a-z0-9_]*$', tool_name):
            return False, "Tool name must start with lowercase letter and contain only lowercase letters, numbers, and underscores"
        
        # Check length
        if len(tool_name) < 3:
            return False, "Tool name must be at least 3 characters"
        
        if len(tool_name) > 64:
            return False, "Tool name must be at most 64 characters"
        
        # Check for conflicts
        if tool_name in existing_tools:
            return False, f"Tool name '{tool_name}' already exists"
        
        # Check reserved names
        reserved = ['self', 'class', 'def', 'import', 'from', 'return', 'tool', 'mcp']
        if tool_name in reserved:
            return False, f"'{tool_name}' is a reserved name"
        
        return True, ""
