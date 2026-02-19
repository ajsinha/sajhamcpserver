"""
SAJHA MCP Server - IBM LiveLink Document Tool Generator v2.8.0

Generates MCP tools that query and download documents from IBM LiveLink (OpenText Content Server)
via REST API and return document content as base64 encoded data.

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
class LiveLinkToolConfig:
    """Configuration for an IBM LiveLink document MCP tool."""
    
    # Basic Info
    tool_name: str
    description: str
    
    # LiveLink Configuration
    server_url: str  # LiveLink server base URL
    
    # Authentication
    auth_type: str = "basic"  # basic, oauth, otds
    username_env: str = "LIVELINK_USERNAME"
    password_env: str = "LIVELINK_PASSWORD"
    oauth_token_env: str = "LIVELINK_OAUTH_TOKEN"  # For OAuth
    
    # Document Query Settings
    default_parent_id: str = ""  # Default folder/container ID
    document_types: List[str] = field(default_factory=list)  # Filter by doc types
    
    # Optional metadata
    version: str = "2.8.0"
    author: str = ""
    tags: List[str] = field(default_factory=list)
    
    # Request options
    timeout_seconds: int = 60
    max_file_size_mb: int = 50  # Max file size to download
    
    # API version
    api_version: str = "v2"  # v1 or v2


class LiveLinkToolGenerator:
    """Generates MCP tools for IBM LiveLink document retrieval."""
    
    AUTH_TYPES = ['basic', 'oauth', 'otds']
    API_VERSIONS = ['v1', 'v2']
    
    def __init__(self, config_dir: str, impl_dir: str):
        """
        Initialize the LiveLink tool generator.
        
        Args:
            config_dir: Directory for JSON tool configurations
            impl_dir: Directory for Python tool implementations
        """
        self.config_dir = config_dir
        self.impl_dir = impl_dir
        
        # Ensure directories exist
        os.makedirs(config_dir, exist_ok=True)
        os.makedirs(impl_dir, exist_ok=True)
    
    def validate_config(self, config: LiveLinkToolConfig) -> List[str]:
        """
        Validate a LiveLink tool configuration.
        
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
        
        # Validate server URL
        if not config.server_url:
            errors.append("Server URL is required")
        elif not config.server_url.startswith(('http://', 'https://')):
            errors.append("Server URL must start with http:// or https://")
        
        # Validate auth type
        if config.auth_type not in self.AUTH_TYPES:
            errors.append(f"Auth type must be one of: {', '.join(self.AUTH_TYPES)}")
        
        # Validate API version
        if config.api_version not in self.API_VERSIONS:
            errors.append(f"API version must be one of: {', '.join(self.API_VERSIONS)}")
        
        # Validate timeout
        if config.timeout_seconds < 10 or config.timeout_seconds > 300:
            errors.append("Timeout must be between 10 and 300 seconds")
        
        # Validate max file size
        if config.max_file_size_mb < 1 or config.max_file_size_mb > 500:
            errors.append("Max file size must be between 1 and 500 MB")
        
        return errors
    
    def _to_class_name(self, tool_name: str) -> str:
        """Convert tool_name to PascalCase class name."""
        return ''.join(word.capitalize() for word in tool_name.split('_'))
    
    def generate_tool_config(self, config: LiveLinkToolConfig) -> Dict[str, Any]:
        """Generate the JSON tool configuration."""
        return {
            "name": config.tool_name,
            "implementation": f"sajha.tools.impl.livelink_{config.tool_name}.LiveLink{self._to_class_name(config.tool_name)}Tool",
            "description": config.description,
            "version": config.version,
            "enabled": True,
            "metadata": {
                "author": config.author or "MCP Studio - LiveLink Generator",
                "category": "Document Management",
                "tags": config.tags or ["livelink", "opentext", "document", "ecm", "generated"],
                "rateLimit": 20,
                "cacheTTL": 0,  # Documents shouldn't be cached
                "requiresApiKey": False,
                "source": "livelink",
                "auth_type": config.auth_type,
                "api_version": config.api_version,
                "generator_version": "2.8.0"
            }
        }
    
    def generate_python_wrapper(self, config: LiveLinkToolConfig) -> str:
        """Generate the Python tool wrapper implementation."""
        
        class_name = self._to_class_name(config.tool_name)
        
        code = f'''"""
SAJHA MCP Server - IBM LiveLink Tool: {config.tool_name}

Query and download documents from IBM LiveLink (OpenText Content Server).
Returns document content as base64 encoded data.

Auto-generated by MCP Studio LiveLink Tool Creator v2.8.0
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
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from sajha.tools.base_mcp_tool import BaseMCPTool

logger = logging.getLogger(__name__)


class LiveLink{class_name}Tool(BaseMCPTool):
    """
    {config.description}
    
    Queries and downloads documents from IBM LiveLink (OpenText Content Server).
    Returns document content as base64 encoded data.
    Auto-generated by MCP Studio LiveLink Tool Creator.
    """
    
    NAME = "{config.tool_name}"
    DESCRIPTION = """{config.description}"""
    VERSION = "{config.version}"
    CATEGORY = "Document Management"
    TAGS = {config.tags if config.tags else ["livelink", "opentext", "document", "ecm", "generated"]}
    
    # LiveLink Configuration
    SERVER_URL = "{config.server_url.rstrip('/')}"
    AUTH_TYPE = "{config.auth_type}"
    USERNAME_ENV = "{config.username_env}"
    PASSWORD_ENV = "{config.password_env}"
    OAUTH_TOKEN_ENV = "{config.oauth_token_env}"
    DEFAULT_PARENT_ID = "{config.default_parent_id}"
    DOCUMENT_TYPES = {config.document_types if config.document_types else []}
    TIMEOUT_SECONDS = {config.timeout_seconds}
    MAX_FILE_SIZE_MB = {config.max_file_size_mb}
    API_VERSION = "{config.api_version}"
    
    INPUT_SCHEMA = {{
        "type": "object",
        "properties": {{
            "action": {{
                "type": "string",
                "enum": ["search", "get", "download", "list"],
                "description": "Action to perform: search (find documents), get (get metadata), download (get content), list (list folder contents)",
                "default": "search"
            }},
            "document_id": {{
                "type": "string",
                "description": "Document/Node ID for get/download actions"
            }},
            "query": {{
                "type": "string",
                "description": "Search query for finding documents"
            }},
            "parent_id": {{
                "type": "string",
                "description": "Parent folder ID for list action"
            }},
            "document_name": {{
                "type": "string",
                "description": "Filter by document name (supports wildcards)"
            }},
            "max_results": {{
                "type": "integer",
                "description": "Maximum number of results to return",
                "default": 25,
                "minimum": 1,
                "maximum": 100
            }}
        }},
        "required": []
    }}
    
    OUTPUT_SCHEMA = {{
        "type": "object",
        "properties": {{
            "success": {{
                "type": "boolean",
                "description": "Whether the operation was successful"
            }},
            "action": {{
                "type": "string",
                "description": "Action that was performed"
            }},
            "document_id": {{
                "type": "string",
                "description": "Document ID (for single document operations)"
            }},
            "document_name": {{
                "type": "string",
                "description": "Document name"
            }},
            "mime_type": {{
                "type": "string",
                "description": "MIME type of the document"
            }},
            "size_bytes": {{
                "type": "integer",
                "description": "Size of the document in bytes"
            }},
            "data": {{
                "type": "string",
                "description": "Base64 encoded document content (for download action)"
            }},
            "metadata": {{
                "type": "object",
                "description": "Document metadata"
            }},
            "results": {{
                "type": "array",
                "description": "List of documents (for search/list actions)"
            }},
            "result_count": {{
                "type": "integer",
                "description": "Number of results"
            }},
            "error": {{
                "type": "string",
                "description": "Error message if operation failed"
            }}
        }}
    }}
    
    LITERATURE = """IBM LiveLink (OpenText Content Server) Document Tool.
Supports searching, listing, retrieving metadata, and downloading documents.
Downloaded documents are returned as base64 encoded data.
Actions: search (find by query), get (metadata), download (content), list (folder contents).
Requires LiveLink credentials via environment variables."""
    
    def __init__(self):
        """Initialize the LiveLink tool."""
        super().__init__()
        self._auth_ticket = None
        self._ticket_expires = 0
    
    def _get_auth_headers(self) -> Optional[Dict[str, str]]:
        """Get authentication headers based on auth type."""
        
        if self.AUTH_TYPE == "oauth":
            token = os.environ.get(self.OAUTH_TOKEN_ENV)
            if not token:
                logger.error(f"Environment variable {{self.OAUTH_TOKEN_ENV}} not set")
                return None
            return {{"Authorization": f"Bearer {{token}}"}}
        
        elif self.AUTH_TYPE == "basic":
            username = os.environ.get(self.USERNAME_ENV)
            password = os.environ.get(self.PASSWORD_ENV)
            if not username or not password:
                logger.error(f"Environment variables {{self.USERNAME_ENV}} and {{self.PASSWORD_ENV}} must be set")
                return None
            
            import base64
            credentials = base64.b64encode(f"{{username}}:{{password}}".encode()).decode()
            return {{"Authorization": f"Basic {{credentials}}"}}
        
        elif self.AUTH_TYPE == "otds":
            # OpenText Directory Services token
            return self._get_otds_token()
        
        return {{}}
    
    def _get_otds_token(self) -> Optional[Dict[str, str]]:
        """Get OTDS authentication token."""
        username = os.environ.get(self.USERNAME_ENV)
        password = os.environ.get(self.PASSWORD_ENV)
        
        if not username or not password:
            logger.error("OTDS credentials not configured")
            return None
        
        # Check cached ticket
        if self._auth_ticket and time.time() < self._ticket_expires - 60:
            return {{"OTCSTicket": self._auth_ticket}}
        
        try:
            auth_url = f"{{self.SERVER_URL}}/api/{{self.API_VERSION}}/auth"
            response = requests.post(
                auth_url,
                data={{"username": username, "password": password}},
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            self._auth_ticket = data.get("ticket")
            self._ticket_expires = time.time() + 3600  # 1 hour default
            
            return {{"OTCSTicket": self._auth_ticket}}
            
        except requests.RequestException as e:
            logger.error(f"OTDS authentication failed: {{e}}")
            return None
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """Make authenticated request to LiveLink API."""
        
        auth_headers = self._get_auth_headers()
        if auth_headers is None:
            raise Exception("Authentication failed - check credentials")
        
        headers = kwargs.pop('headers', {{}})
        headers.update(auth_headers)
        
        url = f"{{self.SERVER_URL}}/api/{{self.API_VERSION}}/{{endpoint.lstrip('/')}}"
        
        return requests.request(
            method,
            url,
            headers=headers,
            timeout=self.TIMEOUT_SECONDS,
            **kwargs
        )
    
    def _search_documents(self, query: str, document_name: str = None, 
                          max_results: int = 25) -> Dict[str, Any]:
        """Search for documents."""
        try:
            params = {{
                "where_type": 144,  # Document type
                "limit": max_results
            }}
            
            if query:
                params["where_name"] = f"contains_{{query}}"
            elif document_name:
                params["where_name"] = document_name
            
            response = self._make_request("GET", "nodes", params=params)
            response.raise_for_status()
            
            data = response.json()
            results = data.get("results", data.get("data", []))
            
            documents = []
            for item in results:
                doc_data = item.get("data", item) if isinstance(item, dict) else item
                properties = doc_data.get("properties", doc_data)
                
                documents.append({{
                    "id": str(properties.get("id", "")),
                    "name": properties.get("name", ""),
                    "type": properties.get("type", ""),
                    "type_name": properties.get("type_name", "Document"),
                    "size": properties.get("size", 0),
                    "create_date": properties.get("create_date", ""),
                    "modify_date": properties.get("modify_date", ""),
                    "parent_id": str(properties.get("parent_id", ""))
                }})
            
            return {{
                "success": True,
                "action": "search",
                "results": documents,
                "result_count": len(documents)
            }}
            
        except requests.RequestException as e:
            return {{"success": False, "error": f"Search failed: {{str(e)}}"}}
    
    def _list_folder(self, parent_id: str, max_results: int = 25) -> Dict[str, Any]:
        """List contents of a folder."""
        try:
            folder_id = parent_id or self.DEFAULT_PARENT_ID
            if not folder_id:
                return {{"success": False, "error": "Parent folder ID is required"}}
            
            response = self._make_request(
                "GET", 
                f"nodes/{{folder_id}}/nodes",
                params={{"limit": max_results}}
            )
            response.raise_for_status()
            
            data = response.json()
            results = data.get("results", data.get("data", []))
            
            items = []
            for item in results:
                doc_data = item.get("data", item) if isinstance(item, dict) else item
                properties = doc_data.get("properties", doc_data)
                
                items.append({{
                    "id": str(properties.get("id", "")),
                    "name": properties.get("name", ""),
                    "type": properties.get("type", ""),
                    "type_name": properties.get("type_name", ""),
                    "size": properties.get("size", 0),
                    "create_date": properties.get("create_date", ""),
                    "modify_date": properties.get("modify_date", "")
                }})
            
            return {{
                "success": True,
                "action": "list",
                "parent_id": folder_id,
                "results": items,
                "result_count": len(items)
            }}
            
        except requests.RequestException as e:
            return {{"success": False, "error": f"List failed: {{str(e)}}"}}
    
    def _get_document_metadata(self, document_id: str) -> Dict[str, Any]:
        """Get document metadata."""
        try:
            if not document_id:
                return {{"success": False, "error": "Document ID is required"}}
            
            response = self._make_request("GET", f"nodes/{{document_id}}")
            response.raise_for_status()
            
            data = response.json()
            doc_data = data.get("results", data.get("data", data))
            if isinstance(doc_data, list):
                doc_data = doc_data[0] if doc_data else {{}}
            
            properties = doc_data.get("data", doc_data).get("properties", doc_data)
            
            return {{
                "success": True,
                "action": "get",
                "document_id": document_id,
                "document_name": properties.get("name", ""),
                "mime_type": properties.get("mime_type", ""),
                "size_bytes": properties.get("size", 0),
                "metadata": {{
                    "type": properties.get("type", ""),
                    "type_name": properties.get("type_name", ""),
                    "create_date": properties.get("create_date", ""),
                    "modify_date": properties.get("modify_date", ""),
                    "created_by": properties.get("create_user_id", ""),
                    "modified_by": properties.get("modify_user_id", ""),
                    "parent_id": str(properties.get("parent_id", "")),
                    "description": properties.get("description", "")
                }}
            }}
            
        except requests.RequestException as e:
            return {{"success": False, "error": f"Get metadata failed: {{str(e)}}"}}
    
    def _download_document(self, document_id: str) -> Dict[str, Any]:
        """Download document content as base64."""
        try:
            if not document_id:
                return {{"success": False, "error": "Document ID is required"}}
            
            # First get metadata to check size
            metadata_result = self._get_document_metadata(document_id)
            if not metadata_result.get("success"):
                return metadata_result
            
            file_size = metadata_result.get("size_bytes", 0)
            max_size = self.MAX_FILE_SIZE_MB * 1024 * 1024
            
            if file_size > max_size:
                return {{
                    "success": False,
                    "error": f"File size ({{file_size}} bytes) exceeds maximum allowed ({{max_size}} bytes)"
                }}
            
            # Download content
            response = self._make_request(
                "GET",
                f"nodes/{{document_id}}/content",
                stream=True
            )
            response.raise_for_status()
            
            # Get content and encode
            content = response.content
            b64_content = base64.b64encode(content).decode('utf-8')
            
            return {{
                "success": True,
                "action": "download",
                "document_id": document_id,
                "document_name": metadata_result.get("document_name", ""),
                "mime_type": metadata_result.get("mime_type", response.headers.get("Content-Type", "")),
                "size_bytes": len(content),
                "data": b64_content,
                "metadata": metadata_result.get("metadata", {{}})
            }}
            
        except requests.RequestException as e:
            return {{"success": False, "error": f"Download failed: {{str(e)}}"}}
    
    async def execute(self, action: str = "search", document_id: str = None,
                     query: str = None, parent_id: str = None,
                     document_name: str = None, max_results: int = 25,
                     **kwargs) -> Dict[str, Any]:
        """
        Execute LiveLink operation.
        
        Args:
            action: Operation to perform (search, get, download, list)
            document_id: Document/Node ID for get/download
            query: Search query
            parent_id: Parent folder ID for list
            document_name: Filter by document name
            max_results: Maximum results to return
        
        Returns:
            Dict containing operation results or error
        """
        try:
            logger.info(f"LiveLink action: {{action}}")
            
            if action == "search":
                return self._search_documents(query, document_name, max_results)
            elif action == "list":
                return self._list_folder(parent_id, max_results)
            elif action == "get":
                return self._get_document_metadata(document_id)
            elif action == "download":
                return self._download_document(document_id)
            else:
                return {{
                    "success": False,
                    "error": f"Unknown action: {{action}}. Use: search, get, download, or list"
                }}
            
        except Exception as e:
            logger.error(f"LiveLink tool error: {{e}}")
            return {{
                "success": False,
                "error": f"Tool execution error: {{str(e)}}"
            }}


# Export the tool class
__all__ = ['LiveLink{class_name}Tool']
'''
        
        return code
    
    def generate_tool(self, config: LiveLinkToolConfig) -> Dict[str, Any]:
        """
        Generate a complete LiveLink tool.
        
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
            python_path = os.path.join(self.impl_dir, f"livelink_{config.tool_name}.py")
            with open(python_path, 'w') as f:
                f.write(python_code)
            created_files['python_impl'] = python_path
            
            logger.info(f"Successfully created LiveLink tool: {config.tool_name}")
            
            return {
                "success": True,
                "message": f"LiveLink tool '{config.tool_name}' created successfully!",
                "files": created_files
            }
            
        except Exception as e:
            logger.error(f"Error creating LiveLink tool: {e}")
            return {
                "success": False,
                "message": f"Error creating tool: {str(e)}",
                "files": {}
            }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> LiveLinkToolConfig:
        """Create LiveLinkToolConfig from dictionary."""
        return LiveLinkToolConfig(
            tool_name=data.get('tool_name', ''),
            description=data.get('description', ''),
            server_url=data.get('server_url', ''),
            auth_type=data.get('auth_type', 'basic'),
            username_env=data.get('username_env', 'LIVELINK_USERNAME'),
            password_env=data.get('password_env', 'LIVELINK_PASSWORD'),
            oauth_token_env=data.get('oauth_token_env', 'LIVELINK_OAUTH_TOKEN'),
            default_parent_id=data.get('default_parent_id', ''),
            document_types=data.get('document_types', []),
            version=data.get('version', '2.8.0'),
            author=data.get('author', ''),
            tags=data.get('tags', []),
            timeout_seconds=data.get('timeout_seconds', 60),
            max_file_size_mb=data.get('max_file_size_mb', 50),
            api_version=data.get('api_version', 'v2')
        )


# Export classes
__all__ = ['LiveLinkToolGenerator', 'LiveLinkToolConfig']
