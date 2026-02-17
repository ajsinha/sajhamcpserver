"""
SAJHA MCP Server - MCP Studio Module v2.4.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

MCP Studio is an innovative feature that allows administrators to create
MCP tools from Python code using the @sajhamcptool decorator, from
REST service definitions, or from database query templates.

Features:
- Visual code editor for tool creation from Python
- REST Service Tool Creator for wrapping external APIs (supports JSON, CSV, XML, text)
- DB Query Tool Creator for database queries (DuckDB, SQLite, PostgreSQL, MySQL)
- Automatic schema generation from function signatures
- Dynamic tool generation (JSON config + Python implementation)
- Safe deployment with conflict detection

Usage - Python Code:
    @sajhamcptool(description="My tool description")
    def my_tool_function(param1: str, param2: int = 10) -> dict:
        '''Tool implementation'''
        return {"result": param1, "count": param2}

Usage - REST Service:
    definition = RESTToolDefinition(
        name="my_api_tool",
        endpoint="https://api.example.com/data",
        method="POST",
        description="Call external API",
        request_schema={"type": "object", "properties": {...}},
        response_schema={"type": "object"},
        response_format="json"  # or "csv", "xml", "text"
    )
    generator = RESTToolGenerator()
    generator.save_tool(definition)

Usage - DB Query:
    definition = DBQueryToolDefinition(
        name="get_sales_data",
        description="Query sales data by date range",
        db_type="duckdb",
        connection_string="data/sales.db",
        query_template="SELECT * FROM sales WHERE date >= '{{start_date}}' AND date <= '{{end_date}}'",
        parameters=[
            DBQueryParameter(name="start_date", param_type="date", description="Start date"),
            DBQueryParameter(name="end_date", param_type="date", description="End date")
        ]
    )
    generator = DBQueryToolGenerator()
    generator.save_tool(definition)
"""

__version__ = '2.4.0'
__author__ = 'Ashutosh Sinha'
__email__ = 'ajsinha@gmail.com'

from .decorator import sajhamcptool
from .code_analyzer import CodeAnalyzer, ToolDefinition
from .code_generator import ToolCodeGenerator
from .rest_tool_generator import RESTToolGenerator, RESTToolDefinition
from .dbquery_tool_generator import DBQueryToolGenerator, DBQueryToolDefinition, DBQueryParameter

__all__ = [
    'sajhamcptool',
    'CodeAnalyzer',
    'ToolDefinition',
    'ToolCodeGenerator',
    'RESTToolGenerator',
    'RESTToolDefinition',
    'DBQueryToolGenerator',
    'DBQueryToolDefinition',
    'DBQueryParameter',
    '__version__'
]
