"""
SAJHA MCP Server - MCP Studio Module v2.8.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

MCP Studio is an innovative feature that allows administrators to create
MCP tools from Python code using the @sajhamcptool decorator, from
REST service definitions, from database query templates, from scripts,
from PowerBI report configurations, from PowerBI DAX queries, or from
IBM LiveLink document configurations.

Features:
- Visual code editor for tool creation from Python
- REST Service Tool Creator for wrapping external APIs (supports JSON, CSV, XML, text)
- DB Query Tool Creator for database queries (DuckDB, SQLite, PostgreSQL, MySQL)
- Script Tool Creator for shell and Python scripts (bash, sh, python, node, perl, ruby)
- PowerBI Report Tool Creator for retrieving reports as PDF/PPTX/PNG in base64
- PowerBI DAX Query Tool Creator for executing DAX queries against datasets
- IBM LiveLink Document Tool Creator for querying and downloading ECM documents
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

Usage - Script Tool:
    config = ScriptToolConfig(
        tool_name="system_info",
        description="Get system information",
        script_type="bash",
        script_content="#!/bin/bash\\necho 'Hello from script!'",
        timeout_seconds=30
    )
    generator = ScriptToolGenerator(config_dir, scripts_dir, impl_dir)
    generator.generate_tool(config)

Usage - PowerBI Report:
    config = PowerBIToolConfig(
        tool_name="sales_report_pdf",
        description="Get monthly sales report as PDF",
        report_name="Monthly Sales Report",
        workspace_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        report_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        tenant_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        client_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        export_format="PDF"
    )
    generator = PowerBIToolGenerator(config_dir, impl_dir)
    generator.generate_tool(config)

Usage - PowerBI DAX Query:
    config = PowerBIDAXToolConfig(
        tool_name="sales_by_region",
        description="Query sales by region",
        dataset_name="Sales Analytics",
        workspace_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        dataset_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
        dax_query="EVALUATE SUMMARIZECOLUMNS(Sales[Region], 'Total', SUM(Sales[Amount]))"
    )
    generator = PowerBIDAXToolGenerator(config_dir, impl_dir)
    generator.generate_tool(config)

Usage - IBM LiveLink Document:
    config = LiveLinkToolConfig(
        tool_name="company_docs",
        description="Query and download company documents",
        server_url="https://livelink.company.com/otcs/cs.exe",
        auth_type="basic"
    )
    generator = LiveLinkToolGenerator(config_dir, impl_dir)
    generator.generate_tool(config)
"""

__version__ = '2.9.6'
__author__ = 'Ashutosh Sinha'
__email__ = 'ajsinha@gmail.com'

from .decorator import sajhamcptool
from .code_analyzer import CodeAnalyzer, ToolDefinition
from .code_generator import ToolCodeGenerator
from .rest_tool_generator import RESTToolGenerator, RESTToolDefinition
from .dbquery_tool_generator import DBQueryToolGenerator, DBQueryToolDefinition, DBQueryParameter
from .script_tool_generator import ScriptToolGenerator, ScriptToolConfig
from .powerbi_tool_generator import PowerBIToolGenerator, PowerBIToolConfig
from .powerbidax_tool_generator import PowerBIDAXToolGenerator, PowerBIDAXToolConfig
from .livelink_tool_generator import LiveLinkToolGenerator, LiveLinkToolConfig

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
    'ScriptToolGenerator',
    'ScriptToolConfig',
    'PowerBIToolGenerator',
    'PowerBIToolConfig',
    'PowerBIDAXToolGenerator',
    'PowerBIDAXToolConfig',
    'LiveLinkToolGenerator',
    'LiveLinkToolConfig',
    '__version__'
]
