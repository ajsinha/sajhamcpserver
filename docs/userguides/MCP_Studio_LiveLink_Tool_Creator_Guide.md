# MCP Studio IBM LiveLink Tool Creator Guide
## SAJHA MCP Server v2.9.8

## Overview

The IBM LiveLink (OpenText Content Server) Tool Creator enables you to create MCP tools that interact with enterprise content management systems. Search documents, browse folders, retrieve metadata, download files, and manage document workflows through a simple visual interface.

## Table of Contents

1. [Getting Started](#getting-started)
2. [LiveLink Authentication](#livelink-authentication)
3. [Document Operations](#document-operations)
4. [Folder Navigation](#folder-navigation)
5. [Search Configuration](#search-configuration)
6. [Workflow Integration](#workflow-integration)
7. [Metadata Management](#metadata-management)
8. [Version Control](#version-control)
9. [Security Configuration](#security-configuration)
10. [Examples](#examples)
11. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Accessing the LiveLink Tool Creator

1. Navigate to `http://localhost:3002/admin/studio`
2. Click on **IBM LiveLink Document Tool** card
3. Or directly access: `http://localhost:3002/admin/studio/livelink`

### Prerequisites

- Admin role access to SAJHA MCP Server
- OpenText Content Server URL and credentials
- API access enabled on Content Server
- Understanding of LiveLink object types and structure

### Supported Versions

| Product | Versions |
|---------|----------|
| OpenText Content Server | 16.x, 21.x, 22.x |
| Livelink ECM | 9.x, 10.x |
| Extended ECM | All versions |

---

## LiveLink Authentication

### Basic Authentication

```json
{
  "authentication": {
    "type": "basic",
    "server_url": "${livelink.server.url}",
    "username": "${livelink.username}",
    "password": "${livelink.password}"
  }
}
```

### OAuth Authentication

```json
{
  "authentication": {
    "type": "oauth",
    "server_url": "${livelink.server.url}",
    "client_id": "${livelink.client.id}",
    "client_secret": "${livelink.client.secret}",
    "token_endpoint": "${livelink.token.url}"
  }
}
```

### Session-Based Authentication

```json
{
  "authentication": {
    "type": "session",
    "server_url": "${livelink.server.url}",
    "username": "${livelink.username}",
    "password": "${livelink.password}",
    "session_timeout": 3600,
    "auto_refresh": true
  }
}
```

### Store Credentials in application.properties

```properties
# LiveLink Server Configuration
livelink.server.url=https://contentserver.company.com/otcs/cs.exe
livelink.username=${LIVELINK_USER}
livelink.password=${LIVELINK_PASSWORD}

# API Configuration
livelink.api.version=v2
livelink.timeout=30
```

---

## Document Operations

### Document Tool Configuration

```json
{
  "name": "livelink_document_tool",
  "display_name": "LiveLink Document Operations",
  "description": "Manage documents in OpenText Content Server",
  "category": "Document Management",
  "version": "2.9.8",
  "implementation": "sajha.tools.impl.livelink_tool.LiveLinkDocumentTool"
}
```

### Available Operations

```json
{
  "operations": {
    "get_document": {
      "description": "Retrieve document metadata and content",
      "parameters": {
        "node_id": {"type": "integer", "required": true}
      }
    },
    "download_document": {
      "description": "Download document content",
      "parameters": {
        "node_id": {"type": "integer", "required": true},
        "version": {"type": "integer", "description": "Specific version (latest if omitted)"}
      }
    },
    "get_metadata": {
      "description": "Get document metadata/categories",
      "parameters": {
        "node_id": {"type": "integer", "required": true}
      }
    },
    "list_versions": {
      "description": "List all versions of a document",
      "parameters": {
        "node_id": {"type": "integer", "required": true}
      }
    }
  }
}
```

### Input Schema

```json
{
  "inputSchema": {
    "type": "object",
    "properties": {
      "operation": {
        "type": "string",
        "enum": ["get_document", "download_document", "get_metadata", "list_versions"],
        "required": true
      },
      "node_id": {
        "type": "integer",
        "description": "LiveLink Node ID"
      },
      "include_content": {
        "type": "boolean",
        "default": false,
        "description": "Include document content in response"
      },
      "content_format": {
        "type": "string",
        "enum": ["base64", "text", "url"],
        "default": "url"
      }
    }
  }
}
```

---

## Folder Navigation

### Folder Browser Tool

```json
{
  "name": "livelink_folder_browser",
  "description": "Browse and navigate LiveLink folder structure",
  "operations": {
    "list_contents": {
      "description": "List folder contents",
      "parameters": {
        "folder_id": {"type": "integer", "required": true},
        "page": {"type": "integer", "default": 1},
        "page_size": {"type": "integer", "default": 50},
        "sort_by": {"type": "string", "enum": ["name", "date", "size", "type"]},
        "sort_order": {"type": "string", "enum": ["asc", "desc"]}
      }
    },
    "get_folder_path": {
      "description": "Get full path to folder",
      "parameters": {
        "folder_id": {"type": "integer", "required": true}
      }
    },
    "get_breadcrumbs": {
      "description": "Get folder hierarchy/breadcrumbs",
      "parameters": {
        "node_id": {"type": "integer", "required": true}
      }
    }
  }
}
```

### Object Types

| Type ID | Object Type | Description |
|---------|-------------|-------------|
| 0 | Folder | Container for documents |
| 1 | Alias | Shortcut to another object |
| 141 | Enterprise Workspace | Root workspace |
| 144 | Document | Standard document |
| 136 | Compound Document | Multi-part document |
| 751 | Email | Email message |
| 848 | Virtual Folder | Dynamic folder |

### Folder Content Response

```json
{
  "folder_id": 12345,
  "folder_name": "Project Documents",
  "path": "/Enterprise/Projects/Project Documents",
  "total_items": 156,
  "page": 1,
  "page_size": 50,
  "contents": [
    {
      "node_id": 12346,
      "name": "Requirements.docx",
      "type": "Document",
      "type_id": 144,
      "size": 245678,
      "created_date": "2024-01-15T10:30:00Z",
      "modified_date": "2024-02-20T14:45:00Z",
      "created_by": "john.smith",
      "modified_by": "jane.doe"
    }
  ]
}
```

---

## Search Configuration

### Search Tool Configuration

```json
{
  "name": "livelink_search",
  "description": "Search documents in LiveLink",
  "version": "2.9.8",
  "search_options": {
    "full_text_enabled": true,
    "metadata_search": true,
    "fuzzy_search": true,
    "highlight_results": true
  }
}
```

### Search Input Schema

```json
{
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "required": true,
        "description": "Search query text"
      },
      "search_type": {
        "type": "string",
        "enum": ["fulltext", "name", "metadata", "combined"],
        "default": "combined"
      },
      "folder_id": {
        "type": "integer",
        "description": "Limit search to specific folder"
      },
      "include_subfolders": {
        "type": "boolean",
        "default": true
      },
      "object_types": {
        "type": "array",
        "items": {"type": "integer"},
        "description": "Filter by object type IDs"
      },
      "date_range": {
        "type": "object",
        "properties": {
          "field": {"type": "string", "enum": ["created", "modified"]},
          "from": {"type": "string", "format": "date"},
          "to": {"type": "string", "format": "date"}
        }
      },
      "metadata_filters": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "category": {"type": "string"},
            "attribute": {"type": "string"},
            "operator": {"type": "string"},
            "value": {}
          }
        }
      },
      "max_results": {
        "type": "integer",
        "default": 50,
        "maximum": 500
      }
    }
  }
}
```

### Search Query Examples

**Full-Text Search:**
```json
{
  "query": "financial report 2024",
  "search_type": "fulltext",
  "max_results": 20
}
```

**Metadata Search:**
```json
{
  "query": "*",
  "search_type": "metadata",
  "metadata_filters": [
    {
      "category": "Document Properties",
      "attribute": "Document Type",
      "operator": "equals",
      "value": "Contract"
    },
    {
      "category": "Document Properties",
      "attribute": "Status",
      "operator": "in",
      "value": ["Active", "Pending"]
    }
  ]
}
```

**Combined Search with Date Range:**
```json
{
  "query": "invoice",
  "search_type": "combined",
  "folder_id": 12345,
  "include_subfolders": true,
  "date_range": {
    "field": "modified",
    "from": "2024-01-01",
    "to": "2024-12-31"
  },
  "object_types": [144]
}
```

---

## Workflow Integration

### Workflow Tool Configuration

```json
{
  "name": "livelink_workflow",
  "description": "Manage LiveLink workflows",
  "operations": {
    "list_workflows": {
      "description": "List available workflow templates"
    },
    "get_workflow_status": {
      "description": "Get workflow status for a document",
      "parameters": {
        "node_id": {"type": "integer", "required": true}
      }
    },
    "initiate_workflow": {
      "description": "Start a workflow on a document",
      "parameters": {
        "node_id": {"type": "integer", "required": true},
        "workflow_id": {"type": "integer", "required": true},
        "comments": {"type": "string"}
      }
    },
    "get_my_tasks": {
      "description": "Get workflow tasks assigned to current user"
    }
  }
}
```

---

## Metadata Management

### Category/Metadata Configuration

```json
{
  "metadata": {
    "categories": {
      "Document Properties": {
        "id": 12345,
        "attributes": {
          "Document Type": {"type": "string", "required": true},
          "Department": {"type": "string"},
          "Confidentiality": {"type": "string", "enum": ["Public", "Internal", "Confidential"]},
          "Expiry Date": {"type": "date"}
        }
      },
      "Project Information": {
        "id": 12346,
        "attributes": {
          "Project Code": {"type": "string"},
          "Project Name": {"type": "string"},
          "Phase": {"type": "string"}
        }
      }
    }
  }
}
```

### Get/Update Metadata

```json
{
  "operations": {
    "get_categories": {
      "description": "Get document categories/metadata"
    },
    "update_metadata": {
      "description": "Update document metadata",
      "parameters": {
        "node_id": {"type": "integer", "required": true},
        "category_id": {"type": "integer", "required": true},
        "attributes": {"type": "object"}
      }
    }
  }
}
```

---

## Version Control

### Version Operations

```json
{
  "operations": {
    "list_versions": {
      "description": "List all versions of a document",
      "parameters": {
        "node_id": {"type": "integer", "required": true}
      }
    },
    "get_version": {
      "description": "Get specific version",
      "parameters": {
        "node_id": {"type": "integer", "required": true},
        "version_number": {"type": "integer", "required": true}
      }
    },
    "compare_versions": {
      "description": "Compare two versions",
      "parameters": {
        "node_id": {"type": "integer", "required": true},
        "version_1": {"type": "integer", "required": true},
        "version_2": {"type": "integer", "required": true}
      }
    }
  }
}
```

---

## Security Configuration

### Access Control

```json
{
  "security": {
    "respect_permissions": true,
    "allowed_operations": ["read", "search"],
    "blocked_operations": ["delete", "move"],
    "audit_logging": true,
    "sensitive_folders": [12345, 12346]
  }
}
```

### User Context

```json
{
  "user_context": {
    "impersonation_enabled": false,
    "pass_through_auth": true,
    "log_user_actions": true
  }
}
```

---

## Examples

### Example 1: Document Search Tool

```json
{
  "name": "contract_search",
  "description": "Search for contracts in LiveLink",
  "version": "2.9.8",
  "server_url": "${livelink.server.url}",
  "default_folder": 98765,
  "search_config": {
    "default_object_types": [144],
    "required_categories": ["Contract Information"],
    "sortable_fields": ["name", "contract_date", "expiry_date", "value"]
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "contract_type": {"type": "string", "enum": ["NDA", "MSA", "SOW", "Amendment"]},
      "status": {"type": "string", "enum": ["Draft", "Active", "Expired", "Terminated"]},
      "min_value": {"type": "number"},
      "max_value": {"type": "number"}
    }
  }
}
```

### Example 2: Project Document Browser

```json
{
  "name": "project_docs_browser",
  "description": "Browse project documents",
  "version": "2.9.8",
  "root_folder": 54321,
  "operations": {
    "list_projects": "List all project folders",
    "get_project_docs": "Get documents for a project",
    "search_in_project": "Search within a project"
  }
}
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| 401 Unauthorized | Invalid credentials | Check username/password |
| 403 Forbidden | No permission | Verify user permissions |
| Node not found | Wrong node ID | Verify node exists |
| Search timeout | Large result set | Add filters, limit results |
| SSL Error | Certificate issue | Add cert to trusted store |

### Debug Configuration

```json
{
  "debug": {
    "log_requests": true,
    "log_responses": false,
    "trace_api_calls": true,
    "capture_timings": true
  }
}
```

### API Testing

```bash
# Test LiveLink API connection
curl -u username:password \
  "https://server/otcs/cs.exe/api/v2/nodes/12345"
```

---

*SAJHA MCP Server v2.9.8 - IBM LiveLink Tool Creator Guide*
*Copyright © 2025-2030 Ashutosh Sinha*
