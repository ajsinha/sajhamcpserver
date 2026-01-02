"""
SAJHA MCP Server - MCP Studio Module v2.2.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

MCP Studio is an innovative feature that allows administrators to create
MCP tools from Python code using the @sajhamcptool decorator.

Features:
- Visual code editor for tool creation
- Automatic schema generation from function signatures
- Dynamic tool generation (JSON config + Python implementation)
- Safe deployment with conflict detection

Usage:
    @sajhamcptool(description="My tool description")
    def my_tool_function(param1: str, param2: int = 10) -> dict:
        '''Tool implementation'''
        return {"result": param1, "count": param2}
"""

__version__ = '2.2.0'
__author__ = 'Ashutosh Sinha'
__email__ = 'ajsinha@gmail.com'

from .decorator import sajhamcptool
from .code_analyzer import CodeAnalyzer, ToolDefinition
from .code_generator import ToolCodeGenerator

__all__ = [
    'sajhamcptool',
    'CodeAnalyzer',
    'ToolDefinition',
    'ToolCodeGenerator',
    '__version__'
]
