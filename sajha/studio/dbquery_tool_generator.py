"""
SAJHA MCP Server - DB Query Tool Generator v2.8.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Generates MCP tools from database query definitions.
Supports DuckDB, SQLite, PostgreSQL, and MySQL databases.
"""

import json
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DBQueryParameter:
    """Definition of a query parameter."""
    name: str
    param_type: str  # string, integer, float, boolean, date, datetime
    description: str
    required: bool = True
    default: Optional[Any] = None
    enum: Optional[List[str]] = None  # For dropdown options


@dataclass
class DBQueryToolDefinition:
    """Definition of a database query-based MCP tool."""
    name: str
    description: str
    db_type: str  # duckdb, sqlite, postgresql, mysql
    connection_string: str  # Connection string or file path
    query_template: str  # SQL query with {{param}} placeholders
    parameters: List[DBQueryParameter]
    category: str = "Database"
    tags: List[str] = field(default_factory=list)
    literature: str = ""  # Context/documentation for AI
    timeout: int = 30
    max_rows: int = 1000
    version: str = "2.8.0"


class DBQueryToolGenerator:
    """Generates MCP tools from database query definitions."""
    
    # Map of parameter types to JSON Schema types
    TYPE_MAP = {
        'string': 'string',
        'integer': 'integer',
        'float': 'number',
        'boolean': 'boolean',
        'date': 'string',
        'datetime': 'string'
    }
    
    # Map of parameter types to Python types
    PYTHON_TYPE_MAP = {
        'string': 'str',
        'integer': 'int',
        'float': 'float',
        'boolean': 'bool',
        'date': 'str',
        'datetime': 'str'
    }
    
    def __init__(self):
        self.config_dir = Path.cwd() / 'config' / 'tools'
        self.impl_dir = Path.cwd() / 'sajha' / 'tools' / 'impl'
    
    def validate_definition(self, definition: DBQueryToolDefinition) -> Tuple[bool, List[str]]:
        """
        Validate a DB Query tool definition.
        
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        
        # Validate tool name
        if not definition.name:
            errors.append("Tool name is required")
        elif not re.match(r'^[a-z][a-z0-9_]*$', definition.name):
            errors.append("Tool name must start with lowercase letter, contain only lowercase letters, numbers, and underscores")
        elif len(definition.name) < 3:
            errors.append("Tool name must be at least 3 characters")
        
        # Validate description
        if not definition.description:
            errors.append("Description is required")
        
        # Validate db_type
        valid_db_types = ['duckdb', 'sqlite', 'postgresql', 'mysql']
        if definition.db_type not in valid_db_types:
            errors.append(f"Invalid database type. Must be one of: {', '.join(valid_db_types)}")
        
        # Validate connection string
        if not definition.connection_string:
            errors.append("Connection string is required")
        
        # Validate query template
        if not definition.query_template:
            errors.append("SQL query template is required")
        else:
            # Check for SQL injection risks (basic validation)
            query_upper = definition.query_template.upper()
            if 'DROP ' in query_upper or 'DELETE ' in query_upper or 'TRUNCATE ' in query_upper:
                errors.append("Query contains potentially dangerous operations (DROP, DELETE, TRUNCATE)")
        
        # Validate parameters
        param_names = set()
        for param in definition.parameters:
            if not param.name:
                errors.append("Parameter name is required")
            elif param.name in param_names:
                errors.append(f"Duplicate parameter name: {param.name}")
            else:
                param_names.add(param.name)
            
            if param.param_type not in self.TYPE_MAP:
                errors.append(f"Invalid parameter type for '{param.name}': {param.param_type}")
        
        # Check that all placeholders in query have matching parameters
        placeholders = set(re.findall(r'\{\{(\w+)\}\}', definition.query_template))
        for placeholder in placeholders:
            if placeholder not in param_names:
                errors.append(f"Query placeholder '{{{{{placeholder}}}}}' has no matching parameter definition")
        
        return (len(errors) == 0, errors)
    
    def generate_json_config(self, definition: DBQueryToolDefinition) -> str:
        """Generate the JSON configuration file content."""
        
        config = {
            "name": definition.name,
            "implementation": f"sajha.tools.impl.dbquery_{definition.name}.DBQuery{self._to_class_name(definition.name)}Tool",
            "description": definition.description,
            "version": definition.version,
            "enabled": True,
            "metadata": {
                "author": "MCP Studio - DB Query Generator",
                "category": definition.category,
                "tags": definition.tags if definition.tags else ["database", "query", "sql", "generated"],
                "rateLimit": 60,
                "cacheTTL": 60,
                "requiresApiKey": False,
                "source": "db_query",
                "db_type": definition.db_type,
                "literature": definition.literature[:500] if definition.literature else ""
            }
        }
        
        return json.dumps(config, indent=2)
    
    def _build_input_schema(self, definition: DBQueryToolDefinition) -> Dict:
        """Build JSON Schema for input parameters."""
        
        properties = {}
        required = []
        
        for param in definition.parameters:
            prop = {
                "type": self.TYPE_MAP.get(param.param_type, "string"),
                "description": param.description
            }
            
            # Add format for date types
            if param.param_type == 'date':
                prop["format"] = "date"
            elif param.param_type == 'datetime':
                prop["format"] = "date-time"
            
            # Add enum if provided
            if param.enum:
                prop["enum"] = param.enum
            
            # Add default if provided
            if param.default is not None:
                prop["default"] = param.default
            
            properties[param.name] = prop
            
            if param.required and param.default is None:
                required.append(param.name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required
        }
    
    def _build_output_schema(self, definition: DBQueryToolDefinition) -> Dict:
        """Build output schema for query results."""
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean", "description": "Whether the query succeeded"},
                "data": {
                    "type": "array",
                    "description": "Query result rows",
                    "items": {"type": "object", "additionalProperties": True}
                },
                "columns": {
                    "type": "array",
                    "description": "Column names from result",
                    "items": {"type": "string"}
                },
                "row_count": {"type": "integer", "description": "Number of rows returned"},
                "query_time_ms": {"type": "number", "description": "Query execution time in milliseconds"},
                "db_type": {"type": "string", "description": "Database type used"}
            },
            "required": ["success", "data", "row_count"]
        }
    
    def generate_python_implementation(self, definition: DBQueryToolDefinition) -> str:
        """Generate the Python implementation file content."""
        
        class_name = f"DBQuery{self._to_class_name(definition.name)}Tool"
        input_schema = self._build_input_schema(definition)
        output_schema = self._build_output_schema(definition)
        
        # Generate parameter validation code
        param_validation_code = self._generate_param_validation_code(definition)
        
        # Generate database-specific connection code
        connection_code = self._generate_connection_code(definition)
        
        # Generate query execution code
        query_execution_code = self._generate_query_execution_code(definition)
        
        # Escape literature for docstring
        literature_escaped = definition.literature.replace('"""', '\\"\\"\\"') if definition.literature else ""
        
        code = f'''"""
SAJHA MCP Server - DB Query Tool: {definition.name}
Generated by MCP Studio DB Query Generator v{definition.version}

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha, Email: ajsinha@gmail.com

Auto-generated tool for database query.
Database Type: {definition.db_type}
"""

import re
import time
import logging
from typing import Dict, Any, List, Optional
from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)


class {class_name}(BaseMCPTool):
    """
    MCP Tool for Database Query: {definition.name}
    
    Database Type: {definition.db_type}
    
    Description: {definition.description}
    
    Literature/Context:
    {literature_escaped[:500]}
    """
    
    def __init__(self, config: Dict = None):
        """Initialize the DB Query tool."""
        super().__init__(config or {{}})
        self._name = "{definition.name}"
        self._description = """{definition.description}"""
        self._db_type = "{definition.db_type}"
        self._connection_string = """{definition.connection_string}"""
        self._timeout = {definition.timeout}
        self._max_rows = {definition.max_rows}
        self._query_template = """{definition.query_template}"""
        
        logger.info(f"Initialized DB Query tool: {{self._name}}")
    
    @property
    def name(self) -> str:
        return self._name
    
    @property
    def description(self) -> str:
        return self._description
    
    def get_input_schema(self) -> Dict:
        """Return the JSON Schema for input validation."""
        return {json.dumps(input_schema, indent=8)}
    
    def get_output_schema(self) -> Dict:
        """Return the JSON Schema for output."""
        return {json.dumps(output_schema, indent=8)}
    
    def execute(self, arguments: Dict) -> Dict:
        """
        Execute the database query.
        
        Args:
            arguments: Dictionary of input parameters
            
        Returns:
            Query results as dictionary
        """
        start_time = time.time()
        
        try:
            # Validate parameters
{self._indent(param_validation_code, 12)}
            
            # Build query with parameter substitution (safely)
            query = self._build_query(arguments)
            
            # Get database connection
{self._indent(connection_code, 12)}
            
            # Execute query
{self._indent(query_execution_code, 12)}
            
            # Calculate execution time
            query_time_ms = (time.time() - start_time) * 1000
            
            return {{
                "success": True,
                "data": rows,
                "columns": columns,
                "row_count": len(rows),
                "query_time_ms": round(query_time_ms, 2),
                "db_type": self._db_type
            }}
            
        except ValueError as e:
            return {{
                "success": False,
                "error": f"Validation error: {{str(e)}}"
            }}
        except Exception as e:
            logger.error(f"Error executing DB Query tool {{self._name}}: {{e}}", exc_info=True)
            return {{
                "success": False,
                "error": f"Query execution error: {{str(e)}}"
            }}
    
    def _build_query(self, arguments: Dict) -> str:
        """Build the SQL query with safe parameter substitution."""
        query = self._query_template
        
        # Replace placeholders with parameter values
        for key, value in arguments.items():
            placeholder = f"{{{{{{key}}}}}}"
            if placeholder in query:
                # Escape string values to prevent SQL injection
                if isinstance(value, str):
                    # Simple escaping - replace single quotes with doubled quotes
                    safe_value = value.replace("'", "''")
                    query = query.replace(placeholder, f"'{{safe_value}}'")
                elif isinstance(value, bool):
                    query = query.replace(placeholder, "TRUE" if value else "FALSE")
                elif value is None:
                    query = query.replace(placeholder, "NULL")
                else:
                    query = query.replace(placeholder, str(value))
        
        return query
'''
        
        return code
    
    def _generate_param_validation_code(self, definition: DBQueryToolDefinition) -> str:
        """Generate parameter validation code."""
        lines = []
        
        for param in definition.parameters:
            if param.required and param.default is None:
                lines.append(f'if "{param.name}" not in arguments or arguments["{param.name}"] is None:')
                lines.append(f'    raise ValueError("Required parameter \'{param.name}\' is missing")')
            
            # Type validation
            if param.param_type == 'integer':
                lines.append(f'if "{param.name}" in arguments and arguments["{param.name}"] is not None:')
                lines.append(f'    arguments["{param.name}"] = int(arguments["{param.name}"])')
            elif param.param_type == 'float':
                lines.append(f'if "{param.name}" in arguments and arguments["{param.name}"] is not None:')
                lines.append(f'    arguments["{param.name}"] = float(arguments["{param.name}"])')
            elif param.param_type == 'boolean':
                lines.append(f'if "{param.name}" in arguments and arguments["{param.name}"] is not None:')
                lines.append(f'    val = arguments["{param.name}"]')
                lines.append(f'    arguments["{param.name}"] = val if isinstance(val, bool) else str(val).lower() in ("true", "1", "yes")')
            
            # Enum validation
            if param.enum:
                lines.append(f'if "{param.name}" in arguments and arguments["{param.name}"] is not None:')
                lines.append(f'    if arguments["{param.name}"] not in {param.enum}:')
                lines.append(f'        raise ValueError(f"Parameter \'{param.name}\' must be one of: {param.enum}")')
        
        if not lines:
            return "pass  # No required parameters"
        
        return '\n'.join(lines)
    
    def _generate_connection_code(self, definition: DBQueryToolDefinition) -> str:
        """Generate database connection code based on db_type."""
        
        if definition.db_type == 'duckdb':
            return '''import duckdb
conn = duckdb.connect(self._connection_string if self._connection_string != ':memory:' else ':memory:')'''
        
        elif definition.db_type == 'sqlite':
            return '''import sqlite3
conn = sqlite3.connect(self._connection_string)
conn.row_factory = sqlite3.Row'''
        
        elif definition.db_type == 'postgresql':
            return '''import psycopg2
import psycopg2.extras
conn = psycopg2.connect(self._connection_string)'''
        
        elif definition.db_type == 'mysql':
            return '''import pymysql
import pymysql.cursors
# Parse connection string: host=localhost;database=mydb;user=root;password=secret
conn_params = dict(item.split('=') for item in self._connection_string.split(';') if '=' in item)
conn = pymysql.connect(
    host=conn_params.get('host', 'localhost'),
    database=conn_params.get('database', ''),
    user=conn_params.get('user', ''),
    password=conn_params.get('password', ''),
    cursorclass=pymysql.cursors.DictCursor
)'''
        
        else:
            return '''raise ValueError(f"Unsupported database type: {self._db_type}")'''
    
    def _generate_query_execution_code(self, definition: DBQueryToolDefinition) -> str:
        """Generate query execution code based on db_type."""
        
        if definition.db_type == 'duckdb':
            return f'''cursor = conn.execute(query)
columns = [desc[0] for desc in cursor.description]
rows = [dict(zip(columns, row)) for row in cursor.fetchmany({definition.max_rows})]
conn.close()'''
        
        elif definition.db_type == 'sqlite':
            return f'''cursor = conn.execute(query)
columns = [desc[0] for desc in cursor.description]
rows = [dict(row) for row in cursor.fetchmany({definition.max_rows})]
conn.close()'''
        
        elif definition.db_type == 'postgresql':
            return f'''cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
cursor.execute(query)
columns = [desc[0] for desc in cursor.description]
rows = cursor.fetchmany({definition.max_rows})
rows = [dict(row) for row in rows]
cursor.close()
conn.close()'''
        
        elif definition.db_type == 'mysql':
            return f'''cursor = conn.cursor()
cursor.execute(query)
columns = [desc[0] for desc in cursor.description] if cursor.description else []
rows = cursor.fetchmany({definition.max_rows})
cursor.close()
conn.close()'''
        
        else:
            return '''raise ValueError(f"Unsupported database type: {self._db_type}")'''
    
    def _to_class_name(self, tool_name: str) -> str:
        """Convert tool_name to ClassName."""
        return ''.join(word.capitalize() for word in tool_name.split('_'))
    
    def _indent(self, code: str, spaces: int) -> str:
        """Indent code block."""
        indent = ' ' * spaces
        lines = code.split('\n')
        return '\n'.join(indent + line if line.strip() else line for line in lines)
    
    def preview_tool(self, definition: DBQueryToolDefinition) -> Dict:
        """
        Generate preview of tool files without saving.
        
        Returns:
            Dictionary with json_content, python_content, and filenames
        """
        is_valid, errors = self.validate_definition(definition)
        
        if not is_valid:
            return {
                'success': False,
                'errors': errors
            }
        
        json_content = self.generate_json_config(definition)
        python_content = self.generate_python_implementation(definition)
        
        return {
            'success': True,
            'json_content': json_content,
            'python_content': python_content,
            'json_filename': f'{definition.name}.json',
            'python_filename': f'dbquery_{definition.name}.py',
            'input_schema': self._build_input_schema(definition),
            'output_schema': self._build_output_schema(definition)
        }
    
    def save_tool(self, definition: DBQueryToolDefinition, overwrite: bool = False) -> Tuple[bool, str, str, str]:
        """
        Save the generated tool files.
        
        Args:
            definition: DB Query tool definition
            overwrite: Whether to overwrite existing files
            
        Returns:
            Tuple of (success, message, json_path, python_path)
        """
        # Validate first
        is_valid, errors = self.validate_definition(definition)
        if not is_valid:
            return (False, f"Validation errors: {', '.join(errors)}", "", "")
        
        # Ensure directories exist
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.impl_dir.mkdir(parents=True, exist_ok=True)
        
        json_path = self.config_dir / f'{definition.name}.json'
        python_path = self.impl_dir / f'dbquery_{definition.name}.py'
        
        # Check for existing files
        if not overwrite:
            if json_path.exists():
                return (False, f"Tool configuration already exists: {json_path}", "", "")
            if python_path.exists():
                return (False, f"Tool implementation already exists: {python_path}", "", "")
        
        try:
            # Generate and save JSON config
            json_content = self.generate_json_config(definition)
            json_path.write_text(json_content, encoding='utf-8')
            logger.info(f"Saved tool config: {json_path}")
            
            # Generate and save Python implementation
            python_content = self.generate_python_implementation(definition)
            python_path.write_text(python_content, encoding='utf-8')
            logger.info(f"Saved tool implementation: {python_path}")
            
            return (True, f"Tool '{definition.name}' saved successfully", str(json_path), str(python_path))
            
        except Exception as e:
            logger.error(f"Error saving tool: {e}", exc_info=True)
            return (False, f"Error saving tool: {str(e)}", "", "")
