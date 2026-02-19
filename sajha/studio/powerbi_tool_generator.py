"""
SAJHA MCP Server - PowerBI Tool Generator v2.8.0

Generates MCP tools that retrieve PowerBI reports as PDF in base64 encoded form.
Supports Azure AD authentication and various PowerBI embedding scenarios.

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
class PowerBIToolConfig:
    """Configuration for a PowerBI report MCP tool."""
    
    # Basic Info
    tool_name: str
    description: str
    report_name: str  # Human-readable report name
    
    # PowerBI Configuration
    workspace_id: str  # PowerBI Workspace/Group ID
    report_id: str  # PowerBI Report ID
    
    # Authentication
    tenant_id: str = ""  # Azure AD Tenant ID
    client_id: str = ""  # Azure AD Application (Client) ID
    client_secret_env: str = "POWERBI_CLIENT_SECRET"  # Environment variable name for client secret
    
    # Optional metadata
    version: str = "2.8.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    
    # Report options
    page_name: str = ""  # Optional: specific page to export
    export_format: str = "PDF"  # PDF, PPTX, PNG
    timeout_seconds: int = 120  # Export can take time
    
    # Filter configuration (optional)
    default_filters: Dict[str, Any] = field(default_factory=dict)


class PowerBIToolGenerator:
    """Generates MCP tools for PowerBI report retrieval."""
    
    SUPPORTED_FORMATS = ['PDF', 'PPTX', 'PNG']
    
    def __init__(self, config_dir: str, impl_dir: str):
        """
        Initialize the PowerBI tool generator.
        
        Args:
            config_dir: Directory for JSON tool configurations
            impl_dir: Directory for Python tool implementations
        """
        self.config_dir = config_dir
        self.impl_dir = impl_dir
        
        # Ensure directories exist
        os.makedirs(config_dir, exist_ok=True)
        os.makedirs(impl_dir, exist_ok=True)
    
    def validate_config(self, config: PowerBIToolConfig) -> List[str]:
        """
        Validate a PowerBI tool configuration.
        
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
        
        # Validate report name
        if not config.report_name:
            errors.append("Report name is required")
        
        # Validate workspace ID
        if not config.workspace_id:
            errors.append("Workspace ID is required")
        elif not self._is_valid_guid(config.workspace_id):
            errors.append("Workspace ID must be a valid GUID format")
        
        # Validate report ID
        if not config.report_id:
            errors.append("Report ID is required")
        elif not self._is_valid_guid(config.report_id):
            errors.append("Report ID must be a valid GUID format")
        
        # Validate tenant ID if provided
        if config.tenant_id and not self._is_valid_guid(config.tenant_id):
            errors.append("Tenant ID must be a valid GUID format")
        
        # Validate client ID if provided
        if config.client_id and not self._is_valid_guid(config.client_id):
            errors.append("Client ID must be a valid GUID format")
        
        # Validate export format
        if config.export_format not in self.SUPPORTED_FORMATS:
            errors.append(f"Export format must be one of: {', '.join(self.SUPPORTED_FORMATS)}")
        
        # Validate timeout
        if config.timeout_seconds < 30 or config.timeout_seconds > 600:
            errors.append("Timeout must be between 30 and 600 seconds")
        
        return errors
    
    def _is_valid_guid(self, value: str) -> bool:
        """Check if a string is a valid GUID format."""
        import re
        guid_pattern = r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
        return bool(re.match(guid_pattern, value))
    
    def _to_class_name(self, tool_name: str) -> str:
        """Convert tool_name to PascalCase class name."""
        return ''.join(word.capitalize() for word in tool_name.split('_'))
    
    def generate_tool_config(self, config: PowerBIToolConfig) -> Dict[str, Any]:
        """Generate the JSON tool configuration."""
        return {
            "name": config.tool_name,
            "implementation": f"sajha.tools.impl.powerbi_{config.tool_name}.PowerBI{self._to_class_name(config.tool_name)}Tool",
            "description": config.description,
            "version": config.version,
            "enabled": True,
            "metadata": {
                "author": config.author or "MCP Studio - PowerBI Generator",
                "category": "PowerBI",
                "tags": config.tags or ["powerbi", "report", "pdf", "analytics", "generated"],
                "rateLimit": 10,  # Lower rate limit for heavy operations
                "cacheTTL": 300,  # 5 minutes cache
                "requiresApiKey": False,
                "source": "powerbi",
                "report_name": config.report_name,
                "export_format": config.export_format,
                "generator_version": "2.8.0"
            }
        }
    
    def generate_python_wrapper(self, config: PowerBIToolConfig) -> str:
        """Generate the Python tool wrapper implementation."""
        
        class_name = self._to_class_name(config.tool_name)
        
        code = f'''"""
SAJHA MCP Server - PowerBI Tool: {config.tool_name}

Retrieves PowerBI report "{config.report_name}" as {config.export_format} in base64 format.

Auto-generated by MCP Studio PowerBI Tool Creator v2.8.0
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""

import os
import sys
import json
import time
import base64
import logging
import requests
from pathlib import Path
from typing import Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)


class PowerBI{class_name}Tool(BaseMCPTool):
    """
    {config.description}
    
    Retrieves PowerBI report as {config.export_format} and returns base64 encoded data.
    Auto-generated by MCP Studio PowerBI Tool Creator.
    """
    
    NAME = "{config.tool_name}"
    DESCRIPTION = """{config.description}"""
    VERSION = "{config.version}"
    CATEGORY = "PowerBI"
    TAGS = {config.tags if config.tags else ["powerbi", "report", "pdf", "analytics", "generated"]}
    
    # PowerBI Configuration
    REPORT_NAME = "{config.report_name}"
    WORKSPACE_ID = "{config.workspace_id}"
    REPORT_ID = "{config.report_id}"
    TENANT_ID = "{config.tenant_id}"
    CLIENT_ID = "{config.client_id}"
    CLIENT_SECRET_ENV = "{config.client_secret_env}"
    EXPORT_FORMAT = "{config.export_format}"
    PAGE_NAME = "{config.page_name}"
    TIMEOUT_SECONDS = {config.timeout_seconds}
    DEFAULT_FILTERS = {json.dumps(config.default_filters)}
    
    # PowerBI API endpoints
    AUTH_URL = "https://login.microsoftonline.com/{{tenant_id}}/oauth2/v2.0/token"
    POWERBI_API_BASE = "https://api.powerbi.com/v1.0/myorg"
    
    INPUT_SCHEMA = {{
        "type": "object",
        "properties": {{
            "report_name": {{
                "type": "string",
                "description": "Optional: Override the default report name for logging purposes",
                "default": "{config.report_name}"
            }},
            "page_name": {{
                "type": "string",
                "description": "Optional: Specific page to export (leave empty for all pages)"
            }},
            "filters": {{
                "type": "object",
                "description": "Optional: Report filters to apply",
                "default": {{}}
            }}
        }},
        "required": []
    }}
    
    OUTPUT_SCHEMA = {{
        "type": "object",
        "properties": {{
            "success": {{
                "type": "boolean",
                "description": "Whether the export was successful"
            }},
            "report_name": {{
                "type": "string",
                "description": "Name of the exported report"
            }},
            "format": {{
                "type": "string",
                "description": "Export format (PDF, PPTX, PNG)"
            }},
            "data": {{
                "type": "string",
                "description": "Base64 encoded report content"
            }},
            "size_bytes": {{
                "type": "integer",
                "description": "Size of the exported file in bytes"
            }},
            "export_time_seconds": {{
                "type": "number",
                "description": "Time taken to export the report"
            }},
            "error": {{
                "type": "string",
                "description": "Error message if export failed"
            }}
        }}
    }}
    
    LITERATURE = """PowerBI Report Export Tool that retrieves the report "{config.report_name}" as {config.export_format} format. 
The report is returned as base64 encoded data which can be decoded and saved as a file.
Requires Azure AD authentication with appropriate PowerBI permissions.
To use, ensure the following environment variables are set:
- {config.client_secret_env}: Azure AD client secret
Or configure service principal with PowerBI API access."""
    
    def __init__(self):
        """Initialize the PowerBI tool."""
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
    
    def _export_report(self, page_name: Optional[str] = None, filters: Optional[Dict] = None) -> Dict[str, Any]:
        """Export the PowerBI report."""
        
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
        
        # Build export request
        export_url = f"{{self.POWERBI_API_BASE}}/groups/{{self.WORKSPACE_ID}}/reports/{{self.REPORT_ID}}/ExportTo"
        
        export_request = {{
            "format": self.EXPORT_FORMAT
        }}
        
        # Add page specification if provided
        effective_page = page_name or self.PAGE_NAME
        if effective_page:
            export_request["powerBIReportConfiguration"] = {{
                "pages": [{{"pageName": effective_page}}]
            }}
        
        # Add filters if provided
        effective_filters = filters or self.DEFAULT_FILTERS
        if effective_filters:
            if "powerBIReportConfiguration" not in export_request:
                export_request["powerBIReportConfiguration"] = {{}}
            export_request["powerBIReportConfiguration"]["reportLevelFilters"] = effective_filters
        
        try:
            # Initiate export
            response = requests.post(export_url, headers=headers, json=export_request, timeout=60)
            response.raise_for_status()
            
            export_data = response.json()
            export_id = export_data.get('id')
            
            if not export_id:
                return {{
                    "success": False,
                    "error": "Failed to initiate export - no export ID returned"
                }}
            
            # Poll for export completion
            status_url = f"{{self.POWERBI_API_BASE}}/groups/{{self.WORKSPACE_ID}}/reports/{{self.REPORT_ID}}/exports/{{export_id}}"
            
            max_attempts = self.TIMEOUT_SECONDS // 5
            for attempt in range(max_attempts):
                time.sleep(5)
                
                status_response = requests.get(status_url, headers=headers, timeout=30)
                status_response.raise_for_status()
                
                status_data = status_response.json()
                status = status_data.get('status')
                
                if status == 'Succeeded':
                    # Get the export file
                    file_url = status_data.get('resourceLocation')
                    if not file_url:
                        return {{
                            "success": False,
                            "error": "Export succeeded but no file URL returned"
                        }}
                    
                    file_response = requests.get(file_url, headers=headers, timeout=60)
                    file_response.raise_for_status()
                    
                    # Encode to base64
                    file_content = file_response.content
                    b64_content = base64.b64encode(file_content).decode('utf-8')
                    
                    export_time = time.time() - start_time
                    
                    return {{
                        "success": True,
                        "report_name": self.REPORT_NAME,
                        "format": self.EXPORT_FORMAT,
                        "data": b64_content,
                        "size_bytes": len(file_content),
                        "export_time_seconds": round(export_time, 2)
                    }}
                
                elif status == 'Failed':
                    error_msg = status_data.get('error', {{}}).get('message', 'Unknown error')
                    return {{
                        "success": False,
                        "error": f"Export failed: {{error_msg}}"
                    }}
                
                # Still running, continue polling
                logger.debug(f"Export status: {{status}}, attempt {{attempt + 1}}/{{max_attempts}}")
            
            # Timeout
            return {{
                "success": False,
                "error": f"Export timed out after {{self.TIMEOUT_SECONDS}} seconds"
            }}
            
        except requests.RequestException as e:
            export_time = time.time() - start_time
            logger.error(f"PowerBI API error: {{e}}")
            return {{
                "success": False,
                "error": f"PowerBI API error: {{str(e)}}",
                "export_time_seconds": round(export_time, 2)
            }}
    
    async def execute(self, report_name: Optional[str] = None, 
                     page_name: Optional[str] = None,
                     filters: Optional[Dict] = None,
                     **kwargs) -> Dict[str, Any]:
        """
        Execute the PowerBI report export.
        
        Args:
            report_name: Optional override for report name (for logging)
            page_name: Optional specific page to export
            filters: Optional report filters to apply
        
        Returns:
            Dict containing success status, base64 encoded report data, or error
        """
        try:
            logger.info(f"Exporting PowerBI report: {{self.REPORT_NAME}}")
            
            result = self._export_report(
                page_name=page_name or kwargs.get('page_name'),
                filters=filters or kwargs.get('filters')
            )
            
            if result.get('success'):
                logger.info(f"Successfully exported report: {{result.get('size_bytes')}} bytes")
            else:
                logger.error(f"Failed to export report: {{result.get('error')}}")
            
            return result
            
        except Exception as e:
            logger.error(f"PowerBI tool error: {{e}}")
            return {{
                "success": False,
                "error": f"Tool execution error: {{str(e)}}"
            }}


# Export the tool class
__all__ = ['PowerBI{class_name}Tool']
'''
        
        return code
    
    def generate_tool(self, config: PowerBIToolConfig) -> Dict[str, Any]:
        """
        Generate a complete PowerBI tool.
        
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
            python_path = os.path.join(self.impl_dir, f"powerbi_{config.tool_name}.py")
            with open(python_path, 'w') as f:
                f.write(python_code)
            created_files['python_impl'] = python_path
            
            logger.info(f"Successfully created PowerBI tool: {config.tool_name}")
            
            return {
                "success": True,
                "message": f"PowerBI tool '{config.tool_name}' created successfully!",
                "files": created_files
            }
            
        except Exception as e:
            logger.error(f"Error creating PowerBI tool: {e}")
            return {
                "success": False,
                "message": f"Error creating tool: {str(e)}",
                "files": {}
            }
    
    def delete_tool(self, tool_name: str) -> Dict[str, Any]:
        """Delete an existing PowerBI tool."""
        deleted_files = []
        
        # Delete JSON config
        json_path = os.path.join(self.config_dir, f"{tool_name}.json")
        if os.path.exists(json_path):
            os.remove(json_path)
            deleted_files.append(json_path)
        
        # Delete Python implementation
        python_path = os.path.join(self.impl_dir, f"powerbi_{tool_name}.py")
        if os.path.exists(python_path):
            os.remove(python_path)
            deleted_files.append(python_path)
        
        if deleted_files:
            return {
                "success": True,
                "message": f"Deleted PowerBI tool '{tool_name}'",
                "deleted_files": deleted_files
            }
        else:
            return {
                "success": False,
                "message": f"PowerBI tool '{tool_name}' not found"
            }
    
    def get_existing_tools(self) -> List[Dict[str, str]]:
        """Get list of existing PowerBI tools."""
        tools = []
        
        if not os.path.exists(self.config_dir):
            return tools
        
        for filename in os.listdir(self.config_dir):
            if filename.endswith('.json'):
                try:
                    filepath = os.path.join(self.config_dir, filename)
                    with open(filepath, 'r') as f:
                        config = json.load(f)
                    
                    # Check if it's a PowerBI tool
                    if config.get('metadata', {}).get('source') == 'powerbi':
                        tools.append({
                            'name': config.get('name', filename[:-5]),
                            'description': config.get('description', ''),
                            'report_name': config.get('metadata', {}).get('report_name', ''),
                            'format': config.get('metadata', {}).get('export_format', 'PDF'),
                            'version': config.get('version', '1.0.0'),
                            'enabled': config.get('enabled', True)
                        })
                except Exception as e:
                    logger.warning(f"Error reading tool config {filename}: {e}")
        
        return tools

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> PowerBIToolConfig:
        """Create PowerBIToolConfig from dictionary."""
        return PowerBIToolConfig(
            tool_name=data.get('tool_name', ''),
            description=data.get('description', ''),
            report_name=data.get('report_name', ''),
            workspace_id=data.get('workspace_id', ''),
            report_id=data.get('report_id', ''),
            tenant_id=data.get('tenant_id', ''),
            client_id=data.get('client_id', ''),
            client_secret_env=data.get('client_secret_env', 'POWERBI_CLIENT_SECRET'),
            version=data.get('version', '2.8.0'),
            author=data.get('author', ''),
            tags=data.get('tags', []),
            page_name=data.get('page_name', ''),
            export_format=data.get('export_format', 'PDF'),
            timeout_seconds=data.get('timeout_seconds', 120),
            default_filters=data.get('default_filters', {})
        )


# Export classes
__all__ = ['PowerBIToolGenerator', 'PowerBIToolConfig']
