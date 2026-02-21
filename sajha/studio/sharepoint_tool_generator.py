"""
SAJHA MCP Server - SharePoint Tool Generator
Version: 2.9.8

Visual tool creator for SharePoint integration tools.
"""

import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SharePointToolConfig:
    """Configuration for a SharePoint tool."""
    name: str
    description: str
    tool_type: str  # documents, lists, sites, search
    site_url: str
    version: str = "2.9.8"
    enabled: bool = True
    
    # Authentication
    auth_type: str = "client_credentials"
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    
    # Tool-specific options
    default_folder: str = "/Shared Documents"
    default_list: str = ""
    allowed_operations: List[str] = field(default_factory=list)
    
    # Security options
    max_file_size_mb: int = 100
    allowed_file_types: List[str] = field(default_factory=list)
    enable_version_control: bool = True
    enable_metadata: bool = True
    
    # Caching
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300
    
    # Metadata
    author: str = "MCP Studio"
    category: str = "Document Management"
    tags: List[str] = field(default_factory=lambda: ["sharepoint", "microsoft", "documents"])


class SharePointToolGenerator:
    """Generator for SharePoint MCP tools."""
    
    TOOL_TYPES = {
        'documents': {
            'implementation': 'sajha.tools.impl.sharepoint_tool.SharePointDocumentTool',
            'operations': [
                'list_files', 'get_file', 'download', 'upload', 'search',
                'get_metadata', 'update_metadata', 'check_out', 'check_in',
                'get_versions', 'delete', 'move', 'copy'
            ],
            'description': 'Document management operations'
        },
        'lists': {
            'implementation': 'sajha.tools.impl.sharepoint_tool.SharePointListTool',
            'operations': [
                'get_lists', 'get_list_items', 'get_item', 'create_item',
                'update_item', 'delete_item', 'get_list_schema', 'query_items'
            ],
            'description': 'List and item management'
        },
        'sites': {
            'implementation': 'sajha.tools.impl.sharepoint_tool.SharePointSiteTool',
            'operations': [
                'get_site_info', 'get_subsites', 'get_users', 'get_groups',
                'get_permissions', 'get_content_types'
            ],
            'description': 'Site administration operations'
        },
        'search': {
            'implementation': 'sajha.tools.impl.sharepoint_tool.SharePointSearchTool',
            'operations': ['all', 'documents', 'people', 'sites'],
            'description': 'Enterprise search operations'
        }
    }
    
    def __init__(self, output_dir: str = None):
        """Initialize the generator."""
        self.output_dir = Path(output_dir) if output_dir else Path("config/tools")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate(self, config: SharePointToolConfig) -> Dict[str, Any]:
        """
        Generate a SharePoint tool configuration.
        
        Args:
            config: Tool configuration
            
        Returns:
            Generated tool configuration as dictionary
        """
        tool_type_info = self.TOOL_TYPES.get(config.tool_type, {})
        
        # Build input schema based on tool type
        input_schema = self._build_input_schema(config)
        
        # Build output schema
        output_schema = self._build_output_schema(config)
        
        # Build full configuration
        tool_config = {
            "name": config.name,
            "description": config.description,
            "category": config.category,
            "version": config.version,
            "enabled": config.enabled,
            "implementation": tool_type_info.get('implementation', ''),
            "site_url": config.site_url if not config.site_url.startswith('${') else config.site_url,
            "authentication": {
                "type": config.auth_type,
                "tenant_id": config.tenant_id if not config.tenant_id.startswith('${') else config.tenant_id,
                "client_id": config.client_id if not config.client_id.startswith('${') else config.client_id,
                "client_secret": config.client_secret if not config.client_secret.startswith('${') else config.client_secret
            },
            "inputSchema": input_schema,
            "outputSchema": output_schema,
            "options": {
                "default_folder": config.default_folder,
                "default_list": config.default_list,
                "max_file_size_mb": config.max_file_size_mb,
                "allowed_file_types": config.allowed_file_types,
                "enable_version_control": config.enable_version_control,
                "enable_metadata": config.enable_metadata
            },
            "caching": {
                "enabled": config.cache_enabled,
                "ttl_seconds": config.cache_ttl_seconds
            },
            "metadata": {
                "author": config.author,
                "category": config.category,
                "tags": config.tags,
                "tool_type": config.tool_type,
                "generator_version": "2.9.8"
            }
        }
        
        return tool_config
    
    def _build_input_schema(self, config: SharePointToolConfig) -> Dict:
        """Build input schema based on tool type."""
        tool_type_info = self.TOOL_TYPES.get(config.tool_type, {})
        operations = config.allowed_operations or tool_type_info.get('operations', [])
        
        base_schema = {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "required": True,
                    "enum": operations,
                    "description": "Operation to perform"
                }
            }
        }
        
        # Add type-specific properties
        if config.tool_type == 'documents':
            base_schema["properties"].update({
                "folder_path": {"type": "string", "description": "Folder path"},
                "file_url": {"type": "string", "description": "File URL"},
                "file_name": {"type": "string", "description": "File name"},
                "query": {"type": "string", "description": "Search query"},
                "metadata": {"type": "object", "description": "Metadata fields"},
                "destination_url": {"type": "string", "description": "Destination for move/copy"}
            })
        elif config.tool_type == 'lists':
            base_schema["properties"].update({
                "list_name": {"type": "string", "description": "List name"},
                "item_id": {"type": "integer", "description": "Item ID"},
                "item_data": {"type": "object", "description": "Item data"},
                "filter": {"type": "string", "description": "OData filter"},
                "select_fields": {"type": "array", "items": {"type": "string"}}
            })
        elif config.tool_type == 'sites':
            base_schema["properties"].update({
                "object_url": {"type": "string", "description": "Object URL for permissions"}
            })
        elif config.tool_type == 'search':
            base_schema["properties"].update({
                "query": {"type": "string", "required": True, "description": "Search query"},
                "search_type": {"type": "string", "enum": ["all", "documents", "people", "sites"]},
                "file_types": {"type": "array", "items": {"type": "string"}},
                "max_results": {"type": "integer", "default": 50}
            })
        
        return base_schema
    
    def _build_output_schema(self, config: SharePointToolConfig) -> Dict:
        """Build output schema."""
        return {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "data": {"type": "object"},
                "results": {"type": "array"},
                "execution_time_ms": {"type": "number"},
                "error": {"type": "string"}
            }
        }
    
    def save(self, config: SharePointToolConfig) -> Path:
        """
        Generate and save tool configuration to file.
        
        Args:
            config: Tool configuration
            
        Returns:
            Path to saved configuration file
        """
        tool_config = self.generate(config)
        
        output_path = self.output_dir / f"{config.name}.json"
        
        with open(output_path, 'w') as f:
            json.dump(tool_config, f, indent=4)
        
        logger.info(f"SharePoint tool saved: {output_path}")
        return output_path
    
    def validate(self, config: SharePointToolConfig) -> List[str]:
        """
        Validate tool configuration.
        
        Args:
            config: Tool configuration
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        if not config.name:
            errors.append("Tool name is required")
        elif not config.name.replace('_', '').isalnum():
            errors.append("Tool name must be alphanumeric with underscores only")
        
        if not config.description:
            errors.append("Description is required")
        
        if config.tool_type not in self.TOOL_TYPES:
            errors.append(f"Invalid tool type: {config.tool_type}")
        
        if not config.site_url and not config.site_url.startswith('${'):
            errors.append("Site URL is required")
        
        if config.auth_type == 'client_credentials':
            if not config.tenant_id and not config.tenant_id.startswith('${'):
                errors.append("Tenant ID required for client credentials auth")
            if not config.client_id and not config.client_id.startswith('${'):
                errors.append("Client ID required for client credentials auth")
        
        return errors
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SharePointToolConfig:
        """Create config from dictionary."""
        return SharePointToolConfig(
            name=data.get('name', ''),
            description=data.get('description', ''),
            tool_type=data.get('tool_type', 'documents'),
            site_url=data.get('site_url', ''),
            version=data.get('version', '2.9.8'),
            enabled=data.get('enabled', True),
            auth_type=data.get('auth_type', 'client_credentials'),
            tenant_id=data.get('tenant_id', ''),
            client_id=data.get('client_id', ''),
            client_secret=data.get('client_secret', ''),
            default_folder=data.get('default_folder', '/Shared Documents'),
            default_list=data.get('default_list', ''),
            allowed_operations=data.get('allowed_operations', []),
            max_file_size_mb=data.get('max_file_size_mb', 100),
            allowed_file_types=data.get('allowed_file_types', []),
            enable_version_control=data.get('enable_version_control', True),
            enable_metadata=data.get('enable_metadata', True),
            cache_enabled=data.get('cache_enabled', True),
            cache_ttl_seconds=data.get('cache_ttl_seconds', 300),
            author=data.get('author', 'MCP Studio'),
            category=data.get('category', 'Document Management'),
            tags=data.get('tags', ['sharepoint', 'microsoft', 'documents'])
        )
