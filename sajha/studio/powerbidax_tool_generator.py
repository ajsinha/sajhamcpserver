"""
SAJHA MCP Server - PowerBI DAX Query Tool Generator v2.8.0

Generates MCP tools that execute DAX queries against PowerBI datasets.
Supports Azure AD authentication and returns query results as JSON.

Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

import os
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class PowerBIDAXToolConfig:
    """Configuration for a PowerBI DAX query MCP tool."""
    
    # Basic Info
    tool_name: str
    description: str
    dataset_name: str  # Human-readable dataset name
    
    # PowerBI Configuration
    workspace_id: str  # PowerBI Workspace/Group ID
    dataset_id: str  # PowerBI Dataset ID
    
    # DAX Query
    dax_query: str  # The DAX query template
    
    # Authentication
    tenant_id: str = ""  # Azure AD Tenant ID
    client_id: str = ""  # Azure AD Application (Client) ID
    client_secret_env: str = "POWERBI_CLIENT_SECRET"  # Environment variable name
    
    # Optional metadata
    version: str = "2.9.8"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    
    # Query options
    timeout_seconds: int = 60
    max_rows: int = 10000
    
    # Parameters (for parameterized DAX queries)
    parameters: List[Dict[str, str]] = field(default_factory=list)


class PowerBIDAXToolGenerator:
    """Generates MCP tools for PowerBI DAX queries."""
    
    def __init__(self, config_dir: str, impl_dir: str):
        """
        Initialize the PowerBI DAX tool generator.
        
        Args:
            config_dir: Directory for JSON tool configurations
            impl_dir: Directory for Python tool implementations
        """
        self.config_dir = config_dir
        self.impl_dir = impl_dir
        
        # Ensure directories exist
        os.makedirs(config_dir, exist_ok=True)
        os.makedirs(impl_dir, exist_ok=True)
    
    def validate_config(self, config: PowerBIDAXToolConfig) -> List[str]:
        """
        Validate a PowerBI DAX tool configuration.
        
        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        
        # Validate tool name
        if not config.tool_name:
            errors.append("Tool name is required")
        elif not config.tool_name.replace('_', '').isalnum():
            errors.append("Tool name must contain only letters, numbers, and underscores")
        elif config.tool_name[0].isdigit():
            errors.append("Tool name cannot start with a number")
        
        # Validate description
        if not config.description:
            errors.append("Description is required")
        
        # Validate dataset name
        if not config.dataset_name:
            errors.append("Dataset name is required")
        
        # Validate workspace ID
        if not config.workspace_id:
            errors.append("Workspace ID is required")
        elif not self._is_valid_guid(config.workspace_id):
            errors.append("Workspace ID must be a valid GUID format")
        
        # Validate dataset ID
        if not config.dataset_id:
            errors.append("Dataset ID is required")
        elif not self._is_valid_guid(config.dataset_id):
            errors.append("Dataset ID must be a valid GUID format")
        
        # Validate DAX query
        if not config.dax_query:
            errors.append("DAX query is required")
        elif not config.dax_query.strip().upper().startswith('EVALUATE'):
            errors.append("DAX query must start with EVALUATE")
        
        # Validate tenant ID
        if config.tenant_id and not self._is_valid_guid(config.tenant_id):
            errors.append("Tenant ID must be a valid GUID format")
        
        # Validate client ID
        if config.client_id and not self._is_valid_guid(config.client_id):
            errors.append("Client ID must be a valid GUID format")
        
        # Validate timeout
        if config.timeout_seconds < 10 or config.timeout_seconds > 300:
            errors.append("Timeout must be between 10 and 300 seconds")
        
        return errors
    
    def _is_valid_guid(self, value: str) -> bool:
        """Check if a string is a valid GUID format."""
        import re
        guid_pattern = r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        return bool(re.match(guid_pattern, value))
    
    def _to_class_name(self, tool_name: str) -> str:
        """Convert tool_name to PascalCase class name."""
        return ''.join(word.capitalize() for word in tool_name.split('_'))
    
    def generate_tool_config(self, config: PowerBIDAXToolConfig) -> Dict[str, Any]:
        """Generate the JSON tool configuration."""
        return {
            "name": config.tool_name,
            "implementation": f"sajha.tools.impl.powerbidax_{config.tool_name}.PowerBIDAX{self._to_class_name(config.tool_name)}Tool",
            "description": config.description,
            "version": config.version,
            "enabled": True,
            "metadata": {
                "author": config.author or "MCP Studio - PowerBI DAX Generator",
                "category": "PowerBI",
                "tags": config.tags or ["powerbi", "dax", "query", "analytics", "generated"],
                "rateLimit": 30,
                "cacheTTL": 60,
                "requiresApiKey": False,
                "source": "powerbi_dax",
                "dataset_name": config.dataset_name,
                "generator_version": "2.9.8"
            }
        }
    
    def generate_python_wrapper(self, config: PowerBIDAXToolConfig) -> str:
        """Generate the Python tool wrapper implementation."""
        
        class_name = self._to_class_name(config.tool_name)
        
        # Build input schema from parameters
        input_properties = {}
        required_params = []
        for param in config.parameters:
            param_name = param.get('name', '')
            param_type = param.get('type', 'string')
            param_desc = param.get('description', f'Parameter: {param_name}')
            param_required = param.get('required', True)
            
            input_properties[param_name] = {
                "type": param_type,
                "description": param_desc
            }
            if param_required:
                required_params.append(param_name)
        
        input_schema = {
            "type": "object",
            "properties": input_properties if input_properties else {
                "parameters": {
                    "type": "object",
                    "description": "Optional parameters for the DAX query",
                    "default": {}
                }
            },
            "required": required_params
        }
        
        # Escape DAX query for embedding
        dax_escaped = config.dax_query.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        
        code = f'''"""
SAJHA MCP Server - PowerBI DAX Tool: {config.tool_name}

Executes DAX query against PowerBI dataset "{config.dataset_name}".

Auto-generated by MCP Studio PowerBI DAX Tool Creator v2.8.0
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

import os
import sys
import json
import time
import logging
import requests
from pathlib import Path
from typing import Dict, Any, Optional, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)


class PowerBIDAX{class_name}Tool(BaseMCPTool):
    """
    {config.description}
    
    Executes DAX query against PowerBI dataset and returns results as JSON.
    Auto-generated by MCP Studio PowerBI DAX Tool Creator.
    """
    
    NAME = "{config.tool_name}"
    DESCRIPTION = """{config.description}"""
    VERSION = "{config.version}"
    CATEGORY = "PowerBI"
    TAGS = {config.tags if config.tags else ["powerbi", "dax", "query", "analytics", "generated"]}
    
    # PowerBI Configuration
    DATASET_NAME = "{config.dataset_name}"
    WORKSPACE_ID = "{config.workspace_id}"
    DATASET_ID = "{config.dataset_id}"
    TENANT_ID = "{config.tenant_id}"
    CLIENT_ID = "{config.client_id}"
    CLIENT_SECRET_ENV = "{config.client_secret_env}"
    TIMEOUT_SECONDS = {config.timeout_seconds}
    MAX_ROWS = {config.max_rows}
    
    # DAX Query Template
    DAX_QUERY = """{dax_escaped}"""
    
    # PowerBI API endpoints
    AUTH_URL = "https://login.microsoftonline.com/{{tenant_id}}/oauth2/v2.0/token"
    POWERBI_API_BASE = "https://api.powerbi.com/v1.0/myorg"
    
    INPUT_SCHEMA = {json.dumps(input_schema, indent=8)}
    
    OUTPUT_SCHEMA = {{
        "type": "object",
        "properties": {{
            "success": {{
                "type": "boolean",
                "description": "Whether the query was successful"
            }},
            "dataset_name": {{
                "type": "string",
                "description": "Name of the queried dataset"
            }},
            "row_count": {{
                "type": "integer",
                "description": "Number of rows returned"
            }},
            "columns": {{
                "type": "array",
                "items": {{"type": "string"}},
                "description": "Column names in the result"
            }},
            "data": {{
                "type": "array",
                "description": "Query result rows"
            }},
            "query_time_seconds": {{
                "type": "number",
                "description": "Time taken to execute the query"
            }},
            "error": {{
                "type": "string",
                "description": "Error message if query failed"
            }}
        }}
    }}
    
    LITERATURE = """PowerBI DAX Query Tool that executes DAX queries against the dataset "{config.dataset_name}".
Returns structured data from PowerBI's analytical engine using Data Analysis Expressions (DAX).
Requires Azure AD authentication with appropriate PowerBI permissions.
The query must start with EVALUATE and return a table result."""
    
    def __init__(self):
        """Initialize the PowerBI DAX tool."""
        super().__init__()
        self._access_token = None
        self._token_expires = 0
    
    def _get_access_token(self) -> Optional[str]:
        """Get Azure AD access token for PowerBI API."""
        
        # Check if we have a valid cached token
        if self._access_token and time.time() < self._token_expires - 60:
            return self._access_token
        
        # Get client secret from environment
        client_secret = os.environ.get(self.CLIENT_SECRET_ENV)
        if not client_secret:
            logger.error(f"Environment variable {{self.CLIENT_SECRET_ENV}} not set")
            return None
        
        if not self.TENANT_ID or not self.CLIENT_ID:
            logger.error("Tenant ID and Client ID must be configured")
            return None
        
        auth_url = self.AUTH_URL.format(tenant_id=self.TENANT_ID)
        
        data = {{
            'grant_type': 'client_credentials',
            'client_id': self.CLIENT_ID,
            'client_secret': client_secret,
            'scope': 'https://analysis.windows.net/powerbi/api/.default'
        }}
        
        try:
            response = requests.post(auth_url, data=data, timeout=30)
            response.raise_for_status()
            
            token_data = response.json()
            self._access_token = token_data.get('access_token')
            self._token_expires = time.time() + token_data.get('expires_in', 3600)
            
            return self._access_token
            
        except requests.RequestException as e:
            logger.error(f"Failed to get access token: {{e}}")
            return None
    
    def _substitute_parameters(self, query: str, params: Dict[str, Any]) -> str:
        """Substitute parameters in DAX query."""
        result = query
        for key, value in params.items():
            placeholder = f"@{{key}}"
            # Handle string values with proper DAX escaping
            if isinstance(value, str):
                escaped_value = value.replace('"', '""')
                result = result.replace(placeholder, f'"{escaped_value}"')
            else:
                result = result.replace(placeholder, str(value))
        return result
    
    def _execute_dax_query(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute the DAX query."""
        
        start_time = time.time()
        
        # Get access token
        access_token = self._get_access_token()
        if not access_token:
            return {{
                "success": False,
                "error": "Failed to authenticate with Azure AD. Check credentials."
            }}
        
        headers = {{
            'Authorization': f'Bearer {{access_token}}',
            'Content-Type': 'application/json'
        }}
        
        # Build query with parameter substitution
        query = self.DAX_QUERY
        if params:
            query = self._substitute_parameters(query, params)
        
        # Execute DAX query
        query_url = f"{{self.POWERBI_API_BASE}}/groups/{{self.WORKSPACE_ID}}/datasets/{{self.DATASET_ID}}/executeQueries"
        
        request_body = {{
            "queries": [
                {{
                    "query": query
                }}
            ],
            "serializerSettings": {{
                "includeNulls": True
            }}
        }}
        
        try:
            response = requests.post(
                query_url,
                headers=headers,
                json=request_body,
                timeout=self.TIMEOUT_SECONDS
            )
            response.raise_for_status()
            
            result = response.json()
            query_time = time.time() - start_time
            
            # Extract results
            if 'results' in result and len(result['results']) > 0:
                tables = result['results'][0].get('tables', [])
                if tables:
                    table = tables[0]
                    rows = table.get('rows', [])
                    columns = [col['name'] for col in table.get('columns', [])] if 'columns' in table else []
                    
                    # If columns not in response, infer from first row
                    if not columns and rows:
                        columns = list(rows[0].keys())
                    
                    return {{
                        "success": True,
                        "dataset_name": self.DATASET_NAME,
                        "row_count": len(rows),
                        "columns": columns,
                        "data": rows[:self.MAX_ROWS],
                        "query_time_seconds": round(query_time, 3)
                    }}
            
            return {{
                "success": True,
                "dataset_name": self.DATASET_NAME,
                "row_count": 0,
                "columns": [],
                "data": [],
                "query_time_seconds": round(query_time, 3)
            }}
            
        except requests.RequestException as e:
            query_time = time.time() - start_time
            error_msg = str(e)
            
            # Try to extract PowerBI error message
            try:
                if hasattr(e, 'response') and e.response is not None:
                    error_data = e.response.json()
                    if 'error' in error_data:
                        error_msg = error_data['error'].get('message', error_msg)
            except:
                pass
            
            logger.error(f"DAX query error: {{error_msg}}")
            return {{
                "success": False,
                "error": f"DAX query error: {{error_msg}}",
                "query_time_seconds": round(query_time, 3)
            }}
    
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the DAX query.
        
        Args:
            **kwargs: Query parameters
        
        Returns:
            Dict containing success status, query results, or error
        """
        try:
            logger.info(f"Executing DAX query against: {{self.DATASET_NAME}}")
            
            # Extract parameters
            params = {{k: v for k, v in kwargs.items() if v is not None}}
            
            result = self._execute_dax_query(params)
            
            if result.get('success'):
                logger.info(f"DAX query returned {{result.get('row_count')}} rows")
            else:
                logger.error(f"DAX query failed: {{result.get('error')}}")
            
            return result
            
        except Exception as e:
            logger.error(f"PowerBI DAX tool error: {{e}}")
            return {{
                "success": False,
                "error": f"Tool execution error: {{str(e)}}"
            }}


# Export the tool class
__all__ = ['PowerBIDAX{class_name}Tool']
'''
        
        return code
    
    def generate_tool(self, config: PowerBIDAXToolConfig) -> Dict[str, Any]:
        """
        Generate a complete PowerBI DAX tool.
        
        Returns:
            Dict with 'success', 'message', and 'files' keys
        """
        # Validate configuration
        errors = self.validate_config(config)
        if errors:
            return {
                "success": False,
                "message": "Validation failed: " + "; ".join(errors),
                "files": {}
            }
        
        try:
            created_files = {}
            
            # Generate JSON config
            json_config = self.generate_tool_config(config)
            json_path = os.path.join(self.config_dir, f"{config.tool_name}.json")
            with open(json_path, 'w') as f:
                json.dump(json_config, f, indent=2)
            created_files['json_config'] = json_path
            
            # Generate Python wrapper
            python_code = self.generate_python_wrapper(config)
            python_path = os.path.join(self.impl_dir, f"powerbidax_{config.tool_name}.py")
            with open(python_path, 'w') as f:
                f.write(python_code)
            created_files['python_impl'] = python_path
            
            logger.info(f"Successfully created PowerBI DAX tool: {config.tool_name}")
            
            return {
                "success": True,
                "message": f"PowerBI DAX tool '{config.tool_name}' created successfully!",
                "files": created_files
            }
            
        except Exception as e:
            logger.error(f"Error creating PowerBI DAX tool: {e}")
            return {
                "success": False,
                "message": f"Error creating tool: {str(e)}",
                "files": {}
            }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> PowerBIDAXToolConfig:
        """Create PowerBIDAXToolConfig from dictionary."""
        return PowerBIDAXToolConfig(
            tool_name=data.get('tool_name', ''),
            description=data.get('description', ''),
            dataset_name=data.get('dataset_name', ''),
            workspace_id=data.get('workspace_id', ''),
            dataset_id=data.get('dataset_id', ''),
            dax_query=data.get('dax_query', ''),
            tenant_id=data.get('tenant_id', ''),
            client_id=data.get('client_id', ''),
            client_secret_env=data.get('client_secret_env', 'POWERBI_CLIENT_SECRET'),
            version=data.get('version', '2.9.8'),
            author=data.get('author', ''),
            tags=data.get('tags', []),
            timeout_seconds=data.get('timeout_seconds', 60),
            max_rows=data.get('max_rows', 10000),
            parameters=data.get('parameters', [])
        )


# Export classes
__all__ = ['PowerBIDAXToolGenerator', 'PowerBIDAXToolConfig']
