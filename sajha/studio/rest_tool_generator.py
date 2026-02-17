"""
SAJHA MCP Server - REST Tool Generator v2.4.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Generates MCP tools from REST service definitions.
Supports JSON, CSV, XML, and plain text response formats.
"""

import json
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RESTToolDefinition:
    """Definition of a REST-based MCP tool."""
    name: str
    endpoint: str
    method: str  # GET, POST, PUT, DELETE
    description: str
    request_schema: Dict
    response_schema: Dict
    category: str = "REST API"
    tags: List[str] = field(default_factory=list)
    api_key: Optional[str] = None
    api_key_header: str = "X-API-Key"
    basic_auth_username: Optional[str] = None
    basic_auth_password: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: int = 30
    content_type: str = "application/json"
    response_format: str = "json"  # json, csv, xml, text
    csv_delimiter: str = ","
    csv_has_header: bool = True
    csv_skip_rows: int = 0  # Number of rows to skip before header/data
    version: str = "2.4.0"


class RESTToolGenerator:
    """Generates MCP tools from REST service definitions."""
    
    def __init__(self):
        self.config_dir = Path.cwd() / 'config' / 'tools'
        self.impl_dir = Path.cwd() / 'sajha' / 'tools' / 'impl'
    
    def validate_definition(self, definition: RESTToolDefinition) -> Tuple[bool, List[str]]:
        """
        Validate a REST tool definition.
        
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
        
        # Validate endpoint
        if not definition.endpoint:
            errors.append("REST endpoint URL is required")
        elif not definition.endpoint.startswith(('http://', 'https://')):
            errors.append("Endpoint must start with http:// or https://")
        
        # Validate method
        if definition.method not in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
            errors.append(f"Invalid HTTP method: {definition.method}")
        
        # Validate description
        if not definition.description:
            errors.append("Description is required")
        
        # Validate request schema for POST/PUT/PATCH
        if definition.method in ['POST', 'PUT', 'PATCH']:
            if not definition.request_schema:
                errors.append("Request schema is required for POST/PUT/PATCH methods")
        
        return (len(errors) == 0, errors)
    
    def generate_json_config(self, definition: RESTToolDefinition) -> str:
        """Generate the JSON configuration file content."""
        
        # Build input schema from request schema
        input_schema = self._build_input_schema(definition)
        
        config = {
            "name": definition.name,
            "implementation": f"sajha.tools.impl.rest_{definition.name}.REST{self._to_class_name(definition.name)}Tool",
            "description": definition.description,
            "version": definition.version,
            "enabled": True,
            "metadata": {
                "author": "MCP Studio - REST Generator",
                "category": definition.category,
                "tags": definition.tags if definition.tags else ["rest", "api", "generated"],
                "rateLimit": 60,
                "cacheTTL": 60,
                "requiresApiKey": bool(definition.api_key),
                "source": "rest_service",
                "endpoint": definition.endpoint,
                "method": definition.method
            }
        }
        
        return json.dumps(config, indent=2)
    
    def generate_python_implementation(self, definition: RESTToolDefinition) -> str:
        """Generate the Python implementation file content."""
        
        class_name = f"REST{self._to_class_name(definition.name)}Tool"
        input_schema = self._build_input_schema(definition)
        
        # Generate auth handling code
        auth_code = self._generate_auth_code(definition)
        
        # Generate headers code
        headers_code = self._generate_headers_code(definition)
        
        # Generate request body code for POST/PUT/PATCH
        body_code = self._generate_body_code(definition)
        
        # Generate response parsing code based on format
        response_parse_code = self._generate_response_parse_code(definition)
        
        # Generate output schema based on response format
        output_schema = self._build_output_schema(definition)
        
        code = f'''"""
SAJHA MCP Server - REST Tool: {definition.name}
Generated by MCP Studio REST Generator v{definition.version}

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha, Email: ajsinha@gmail.com

Auto-generated tool for REST endpoint: {definition.endpoint}
Response Format: {definition.response_format}
"""

import csv
import io
import json
import logging
import requests
from typing import Dict, Any, Optional, List
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.tools.http_utils import safe_json_response, safe_decode_response, ENCODINGS_DEFAULT

logger = logging.getLogger(__name__)


class {class_name}(BaseMCPTool):
    """
    MCP Tool for REST Service: {definition.name}
    
    Endpoint: {definition.endpoint}
    Method: {definition.method}
    Response Format: {definition.response_format}
    
    Description: {definition.description}
    """
    
    def __init__(self, config: Dict = None):
        """Initialize the REST tool."""
        super().__init__(config or {{}})
        self._name = "{definition.name}"
        self._description = """{definition.description}"""
        self._endpoint = "{definition.endpoint}"
        self._method = "{definition.method}"
        self._timeout = {definition.timeout}
        self._content_type = "{definition.content_type}"
        self._response_format = "{definition.response_format}"
        self._csv_delimiter = "{definition.csv_delimiter}"
        self._csv_has_header = {definition.csv_has_header}
        self._csv_skip_rows = {definition.csv_skip_rows}
        
        # Authentication
{self._indent(auth_code, 8)}
        
        # Custom headers
{self._indent(headers_code, 8)}
        
        logger.info(f"Initialized REST tool: {{self._name}}")
    
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
        Execute the REST API call.
        
        Args:
            arguments: Dictionary of input parameters
            
        Returns:
            API response as dictionary
        """
        try:
            # Build request URL (supports path parameters)
            url = self._build_url(arguments)
            
            # Build headers
            headers = self._build_headers()
            
            # Build request body for POST/PUT/PATCH
{self._indent(body_code, 12)}
            
            # Make the request
            logger.info(f"Calling REST endpoint: {{self._method}} {{url}}")
            
            response = requests.request(
                method=self._method,
                url=url,
                headers=headers,
                json=body if self._method in ['POST', 'PUT', 'PATCH'] and body else None,
                params=arguments if self._method == 'GET' else None,
                timeout=self._timeout,
                auth=self._auth if hasattr(self, '_auth') and self._auth else None
            )
            
            # Check for errors
            response.raise_for_status()
            
            # Parse response based on format
{self._indent(response_parse_code, 12)}
            
        except requests.exceptions.Timeout:
            return {{
                "success": False,
                "error": f"Request timed out after {{self._timeout}} seconds",
                "endpoint": self._endpoint
            }}
        except requests.exceptions.HTTPError as e:
            return {{
                "success": False,
                "error": f"HTTP error: {{e.response.status_code}} - {{e.response.reason}}",
                "status_code": e.response.status_code,
                "response_text": e.response.text[:500] if e.response.text else None
            }}
        except requests.exceptions.RequestException as e:
            return {{
                "success": False,
                "error": f"Request failed: {{str(e)}}"
            }}
        except Exception as e:
            logger.error(f"Error executing REST tool {{self._name}}: {{e}}", exc_info=True)
            return {{
                "success": False,
                "error": f"Unexpected error: {{str(e)}}"
            }}
    
    def _parse_csv_response(self, text: str) -> Dict:
        """Parse CSV response into structured data."""
        try:
            # Skip rows if configured
            lines = text.strip().split('\\n')
            if self._csv_skip_rows > 0:
                lines = lines[self._csv_skip_rows:]
            text = '\\n'.join(lines)
            
            reader = csv.reader(io.StringIO(text), delimiter=self._csv_delimiter)
            rows = list(reader)
            
            if not rows:
                return {{"rows": [], "columns": [], "row_count": 0}}
            
            if self._csv_has_header:
                columns = [col.strip() for col in rows[0]]
                data_rows = rows[1:]
            else:
                # Generate column names
                columns = [f"column_{{i+1}}" for i in range(len(rows[0]))]
                data_rows = rows
            
            # Convert to list of dictionaries
            parsed_rows = []
            for row in data_rows:
                if len(row) == len(columns):
                    row_dict = {{}}
                    for i, col in enumerate(columns):
                        value = row[i].strip()
                        # Try to convert to number
                        try:
                            if '.' in value:
                                row_dict[col] = float(value)
                            else:
                                row_dict[col] = int(value)
                        except ValueError:
                            row_dict[col] = value
                    parsed_rows.append(row_dict)
            
            return {{
                "rows": parsed_rows,
                "columns": columns,
                "row_count": len(parsed_rows)
            }}
        except Exception as e:
            logger.error(f"Error parsing CSV: {{e}}")
            return {{"raw_text": text, "parse_error": str(e)}}
    
    def _build_url(self, arguments: Dict) -> str:
        """Build the request URL with path parameters."""
        url = self._endpoint
        
        # Replace path parameters like {{param_name}} in URL
        import re
        path_params = re.findall(r'\\{{(\\w+)\\}}', url)
        for param in path_params:
            if param in arguments:
                url = url.replace(f'{{{{{param}}}}}', str(arguments[param]))
        
        return url
    
    def _build_headers(self) -> Dict[str, str]:
        """Build request headers."""
        accept_header = 'application/json'
        if self._response_format == 'csv':
            accept_header = 'text/csv, application/csv, text/plain'
        elif self._response_format == 'xml':
            accept_header = 'application/xml, text/xml'
        elif self._response_format == 'text':
            accept_header = 'text/plain'
        
        headers = {{
            'Content-Type': self._content_type,
            'Accept': accept_header,
            'User-Agent': 'SAJHA-MCP-Server/{definition.version}'
        }}
        
        # Add API key header if configured
        if hasattr(self, '_api_key') and self._api_key:
            headers[self._api_key_header] = self._api_key
        
        # Add custom headers
        if hasattr(self, '_custom_headers'):
            headers.update(self._custom_headers)
        
        return headers
'''
        
        return code
    
    def _build_input_schema(self, definition: RESTToolDefinition) -> Dict:
        """Build JSON Schema for input parameters."""
        
        schema = {
            "type": "object",
            "properties": {},
            "required": []
        }
        
        # For GET requests, use response schema to infer query params
        # For POST/PUT/PATCH, use request schema
        source_schema = definition.request_schema or {}
        
        if source_schema.get('properties'):
            schema['properties'] = source_schema['properties']
            schema['required'] = source_schema.get('required', [])
        elif source_schema.get('type') == 'object':
            schema = source_schema
        else:
            # Default fallback - allow any properties
            schema['additionalProperties'] = True
        
        return schema
    
    def _generate_auth_code(self, definition: RESTToolDefinition) -> str:
        """Generate authentication setup code."""
        lines = []
        
        if definition.api_key:
            lines.append(f'self._api_key = "{definition.api_key}"')
            lines.append(f'self._api_key_header = "{definition.api_key_header}"')
        else:
            lines.append('self._api_key = None')
            lines.append('self._api_key_header = "X-API-Key"')
        
        if definition.basic_auth_username and definition.basic_auth_password:
            lines.append(f'self._auth = ("{definition.basic_auth_username}", "{definition.basic_auth_password}")')
        else:
            lines.append('self._auth = None')
        
        return '\n'.join(lines)
    
    def _generate_headers_code(self, definition: RESTToolDefinition) -> str:
        """Generate custom headers setup code."""
        if definition.headers:
            headers_str = json.dumps(definition.headers, indent=4)
            return f'self._custom_headers = {headers_str}'
        else:
            return 'self._custom_headers = {}'
    
    def _generate_body_code(self, definition: RESTToolDefinition) -> str:
        """Generate request body building code."""
        if definition.method in ['POST', 'PUT', 'PATCH']:
            return '''body = {}
            # Build body from arguments based on request schema
            if arguments:
                for key, value in arguments.items():
                    body[key] = value'''
        else:
            return 'body = None'
    
    def _generate_response_parse_code(self, definition: RESTToolDefinition) -> str:
        """Generate response parsing code based on response format."""
        if definition.response_format == 'csv':
            return '''# Parse CSV response
text = safe_decode_response(response, ENCODINGS_DEFAULT)
result = self._parse_csv_response(text)

return {
    "success": True,
    "status_code": response.status_code,
    "format": "csv",
    "data": result.get("rows", []),
    "columns": result.get("columns", []),
    "row_count": result.get("row_count", 0),
    "endpoint": url,
    "method": self._method
}'''
        elif definition.response_format == 'xml':
            return '''# Parse XML response (return as text with structure info)
text = safe_decode_response(response, ENCODINGS_DEFAULT)
# Basic XML parsing - convert to dict-like structure
try:
    import xml.etree.ElementTree as ET
    root = ET.fromstring(text)
    result = {"root_tag": root.tag, "children": [child.tag for child in root]}
except:
    result = {"raw_xml": text}

return {
    "success": True,
    "status_code": response.status_code,
    "format": "xml",
    "data": result,
    "endpoint": url,
    "method": self._method
}'''
        elif definition.response_format == 'text':
            return '''# Return plain text response
text = safe_decode_response(response, ENCODINGS_DEFAULT)

return {
    "success": True,
    "status_code": response.status_code,
    "format": "text",
    "data": text,
    "content_length": len(text),
    "endpoint": url,
    "method": self._method
}'''
        else:  # json (default)
            return '''# Parse JSON response
try:
    result = safe_json_response(response, ENCODINGS_DEFAULT)
except:
    result = {"raw_response": response.text}

return {
    "success": True,
    "status_code": response.status_code,
    "format": "json",
    "data": result,
    "endpoint": url,
    "method": self._method
}'''
    
    def _build_output_schema(self, definition: RESTToolDefinition) -> Dict:
        """Build output schema based on response format."""
        base_schema = {
            "type": "object",
            "properties": {
                "success": {"type": "boolean", "description": "Whether the request succeeded"},
                "status_code": {"type": "integer", "description": "HTTP status code"},
                "format": {"type": "string", "description": "Response format (json, csv, xml, text)"},
                "endpoint": {"type": "string", "description": "The endpoint URL called"},
                "method": {"type": "string", "description": "HTTP method used"}
            },
            "required": ["success", "status_code", "format"]
        }
        
        if definition.response_format == 'csv':
            base_schema["properties"]["data"] = {
                "type": "array",
                "description": "Parsed CSV rows as array of objects",
                "items": {"type": "object", "additionalProperties": True}
            }
            base_schema["properties"]["columns"] = {
                "type": "array",
                "description": "Column names from CSV",
                "items": {"type": "string"}
            }
            base_schema["properties"]["row_count"] = {
                "type": "integer",
                "description": "Number of data rows"
            }
        elif definition.response_format == 'text':
            base_schema["properties"]["data"] = {
                "type": "string",
                "description": "Plain text response content"
            }
            base_schema["properties"]["content_length"] = {
                "type": "integer",
                "description": "Length of text content"
            }
        else:  # json or xml
            # Use user-provided schema or default
            if definition.response_schema and definition.response_schema.get('properties'):
                base_schema["properties"]["data"] = definition.response_schema
            else:
                base_schema["properties"]["data"] = {
                    "type": "object",
                    "description": "Response data",
                    "additionalProperties": True
                }
        
        return base_schema
    
    def _to_class_name(self, tool_name: str) -> str:
        """Convert tool_name to ClassName."""
        return ''.join(word.capitalize() for word in tool_name.split('_'))
    
    def _indent(self, code: str, spaces: int) -> str:
        """Indent code block."""
        indent = ' ' * spaces
        lines = code.split('\n')
        return '\n'.join(indent + line if line.strip() else line for line in lines)
    
    def preview_tool(self, definition: RESTToolDefinition) -> Dict:
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
            'python_filename': f'rest_{definition.name}.py'
        }
    
    def save_tool(self, definition: RESTToolDefinition, overwrite: bool = False) -> Tuple[bool, str, str, str]:
        """
        Save the generated tool files.
        
        Args:
            definition: REST tool definition
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
        python_path = self.impl_dir / f'rest_{definition.name}.py'
        
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
