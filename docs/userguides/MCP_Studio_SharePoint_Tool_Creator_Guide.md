# MCP Studio SharePoint Tool Creator Guide
## SAJHA MCP Server v2.9.8

## Overview

The SharePoint Tool Creator enables you to build MCP tools that integrate with Microsoft SharePoint and Microsoft 365. Create powerful document management, list operations, site administration, and enterprise search tools through a visual interface without writing API-level code.

## Table of Contents

1. [Getting Started](#getting-started)
2. [SharePoint Integration Overview](#sharepoint-integration-overview)
3. [Azure AD Setup](#azure-ad-setup)
4. [Document Tools](#document-tools)
5. [List Tools](#list-tools)
6. [Site Tools](#site-tools)
7. [Search Tools](#search-tools)
8. [Authentication Configuration](#authentication-configuration)
9. [Security Best Practices](#security-best-practices)
10. [Examples](#examples)
11. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Accessing the SharePoint Tool Creator

1. Navigate to `http://localhost:3002/admin/studio`
2. Click on **SharePoint** card
3. Or directly access: `http://localhost:3002/admin/studio/sharepoint`

### Prerequisites

- Admin role access to SAJHA MCP Server
- Microsoft 365 / SharePoint Online subscription
- Azure Active Directory tenant access
- Azure AD App Registration with SharePoint permissions
- Understanding of SharePoint site structure

### Supported SharePoint Versions

| Platform | Support Level |
|----------|---------------|
| **SharePoint Online** | Full support |
| **Microsoft 365** | Full support |
| **SharePoint 2019** | Partial (REST API) |
| **SharePoint 2016** | Limited |

---

## SharePoint Integration Overview

### Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌─────────────┐
│  MCP Client │────▶│  SharePoint  │────▶│  Microsoft      │────▶│  SharePoint │
│  (Claude)   │◀────│  Tool        │◀────│  Graph API      │◀────│  Online     │
└─────────────┘     └──────────────┘     └─────────────────┘     └─────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │  Azure AD    │
                    │  Auth        │
                    └──────────────┘
```

### Tool Types

| Type | Description | Use Cases |
|------|-------------|-----------|
| **Documents** | File operations | Upload, download, search, version control |
| **Lists** | List/item management | CRUD operations, queries, schema |
| **Sites** | Site administration | Users, groups, permissions, subsites |
| **Search** | Enterprise search | Full-text search across all content |

---

## Azure AD Setup

### Step 1: Create App Registration

1. Go to [Azure Portal](https://portal.azure.com)
2. Navigate to **Azure Active Directory** → **App registrations**
3. Click **New registration**
4. Configure:
   - **Name**: `SAJHA SharePoint MCP Tool`
   - **Supported account types**: Accounts in this organizational directory only
   - **Redirect URI**: Leave blank for now

### Step 2: Configure API Permissions

Add the following Microsoft Graph permissions:

**Application Permissions (Recommended for server-to-server):**

| Permission | Type | Description |
|------------|------|-------------|
| `Sites.Read.All` | Application | Read all site collections |
| `Sites.ReadWrite.All` | Application | Read/write all site collections |
| `Files.Read.All` | Application | Read all files |
| `Files.ReadWrite.All` | Application | Read/write all files |
| `User.Read.All` | Application | Read all users |
| `Group.Read.All` | Application | Read all groups |

**Delegated Permissions (For user context):**

| Permission | Type | Description |
|------------|------|-------------|
| `Sites.Read.All` | Delegated | Read sites on behalf of user |
| `Files.ReadWrite` | Delegated | Read/write user's files |

### Step 3: Grant Admin Consent

1. In the App Registration, go to **API permissions**
2. Click **Grant admin consent for [Your Org]**
3. Confirm the consent

### Step 4: Create Client Secret

1. Go to **Certificates & secrets**
2. Click **New client secret**
3. Set description and expiration
4. **Copy the secret value immediately** (shown only once)

### Step 5: Note Required Values

Record these values for SAJHA configuration:

```properties
# Add to application.properties
azure.tenant.id=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
sharepoint.client.id=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
sharepoint.client.secret=your-client-secret-value
sharepoint.site.url=https://yourtenant.sharepoint.com/sites/yoursite
```

---

## Document Tools

### Creating a Document Tool

1. Select **Documents** as tool type
2. Configure basic information:
   - Tool name: `project_docs`
   - Description: `Manage project documents in SharePoint`
3. Set SharePoint connection
4. Select operations to enable

### Available Operations

| Operation | Description | Parameters |
|-----------|-------------|------------|
| `list_files` | List files in a folder | `folder_path`, `recursive` |
| `get_file` | Get file properties | `file_url` |
| `download` | Download file content | `file_url`, `return_content` |
| `upload` | Upload new file | `folder_path`, `file_name`, `content_base64` |
| `search` | Search documents | `query`, `file_types`, `max_results` |
| `get_metadata` | Get file metadata | `file_url` |
| `update_metadata` | Update metadata | `file_url`, `metadata` |
| `check_out` | Check out file | `file_url` |
| `check_in` | Check in file | `file_url`, `comment` |
| `get_versions` | List file versions | `file_url` |
| `delete` | Delete file | `file_url`, `recycle` |
| `move` | Move file | `source_url`, `destination_url` |
| `copy` | Copy file | `source_url`, `destination_url` |

### Document Tool Configuration

```json
{
  "name": "sharepoint_project_docs",
  "description": "Manage project documents in SharePoint",
  "tool_type": "documents",
  "version": "2.9.8",
  "site_url": "${sharepoint.site.url}",
  "authentication": {
    "type": "client_credentials",
    "tenant_id": "${azure.tenant.id}",
    "client_id": "${sharepoint.client.id}",
    "client_secret": "${sharepoint.client.secret}"
  },
  "options": {
    "default_folder": "/Shared Documents/Projects",
    "allowed_operations": [
      "list_files", "get_file", "download", "search",
      "get_metadata", "get_versions"
    ],
    "max_file_size_mb": 100,
    "allowed_file_types": ["docx", "pdf", "xlsx", "pptx"]
  }
}
```

### Usage Examples

**List Files:**
```json
{
  "operation": "list_files",
  "folder_path": "/Shared Documents/Projects/2024"
}
```

**Search Documents:**
```json
{
  "operation": "search",
  "query": "quarterly report",
  "file_types": ["pdf", "docx"],
  "max_results": 20
}
```

**Download File:**
```json
{
  "operation": "download",
  "file_url": "/sites/team/Shared Documents/report.pdf",
  "return_content": true
}
```

---

## List Tools

### Creating a List Tool

1. Select **Lists** as tool type
2. Configure connection
3. Set default list name (optional)
4. Select operations

### Available Operations

| Operation | Description | Parameters |
|-----------|-------------|------------|
| `get_lists` | List all lists in site | - |
| `get_list_items` | Get items from list | `list_name`, `top`, `skip` |
| `get_item` | Get single item | `list_name`, `item_id` |
| `create_item` | Create new item | `list_name`, `item_data` |
| `update_item` | Update item | `list_name`, `item_id`, `item_data` |
| `delete_item` | Delete item | `list_name`, `item_id` |
| `get_list_schema` | Get list fields | `list_name` |
| `query_items` | Query with OData filter | `list_name`, `filter`, `select_fields` |

### List Tool Configuration

```json
{
  "name": "sharepoint_tasks",
  "description": "Manage SharePoint task lists",
  "tool_type": "lists",
  "version": "2.9.8",
  "site_url": "${sharepoint.site.url}",
  "options": {
    "default_list": "Tasks",
    "allowed_operations": [
      "get_lists", "get_list_items", "get_item",
      "create_item", "update_item", "query_items"
    ]
  }
}
```

### Usage Examples

**Get All Lists:**
```json
{
  "operation": "get_lists"
}
```

**Query Items with Filter:**
```json
{
  "operation": "query_items",
  "list_name": "Projects",
  "filter": "Status eq 'Active' and Priority eq 'High'",
  "select_fields": ["Title", "Status", "DueDate", "AssignedTo"]
}
```

**Create Item:**
```json
{
  "operation": "create_item",
  "list_name": "Tasks",
  "item_data": {
    "Title": "Review Q4 Report",
    "Status": "Not Started",
    "Priority": "High",
    "DueDate": "2024-12-15"
  }
}
```

### OData Filter Examples

| Filter | Description |
|--------|-------------|
| `Status eq 'Active'` | Equal to value |
| `Priority ne 'Low'` | Not equal |
| `Created gt '2024-01-01'` | Greater than date |
| `Title contains 'Report'` | Contains text |
| `AssignedTo eq null` | Is null |
| `Status eq 'Active' and Priority eq 'High'` | AND condition |
| `Status eq 'Draft' or Status eq 'Pending'` | OR condition |

---

## Site Tools

### Creating a Site Tool

1. Select **Sites** as tool type
2. Configure site URL
3. Select site administration operations

### Available Operations

| Operation | Description | Output |
|-----------|-------------|--------|
| `get_site_info` | Get site details | Title, URL, template, created date |
| `get_subsites` | List subsites | Child sites with URLs |
| `get_users` | List site users | Users with roles |
| `get_groups` | List site groups | SharePoint groups |
| `get_permissions` | Get permissions | Role assignments |
| `get_content_types` | List content types | Available content types |

### Site Tool Configuration

```json
{
  "name": "sharepoint_site_admin",
  "description": "SharePoint site administration",
  "tool_type": "sites",
  "version": "2.9.8",
  "site_url": "${sharepoint.site.url}",
  "options": {
    "allowed_operations": [
      "get_site_info", "get_subsites", "get_users",
      "get_groups", "get_content_types"
    ]
  }
}
```

### Usage Examples

**Get Site Information:**
```json
{
  "operation": "get_site_info"
}
```

**Response:**
```json
{
  "success": true,
  "title": "Project Team Site",
  "description": "Collaboration site for project team",
  "url": "https://tenant.sharepoint.com/sites/projectteam",
  "created": "2024-01-15T10:30:00Z",
  "language": 1033,
  "template": "STS#3"
}
```

---

## Search Tools

### Creating a Search Tool

1. Select **Search** as tool type
2. Configure search options
3. Select search scopes

### Search Types

| Type | Description | Best For |
|------|-------------|----------|
| `all` | Search everything | General queries |
| `documents` | Files only | Document discovery |
| `people` | Users/contacts | Finding people |
| `sites` | Sites only | Site discovery |

### Search Tool Configuration

```json
{
  "name": "sharepoint_search",
  "description": "Enterprise search across SharePoint",
  "tool_type": "search",
  "version": "2.9.8",
  "site_url": "${sharepoint.site.url}",
  "options": {
    "search_types": ["all", "documents", "people", "sites"],
    "max_results": 100,
    "highlight_results": true
  }
}
```

### Usage Examples

**Search All Content:**
```json
{
  "query": "quarterly budget 2024",
  "search_type": "all",
  "max_results": 50
}
```

**Search Documents by Type:**
```json
{
  "query": "project plan",
  "search_type": "documents",
  "file_types": ["docx", "pdf"],
  "max_results": 20
}
```

**Search People:**
```json
{
  "query": "project manager",
  "search_type": "people",
  "max_results": 10
}
```

---

## Authentication Configuration

### Client Credentials Flow (Recommended)

Best for server-to-server integration without user interaction.

```json
{
  "authentication": {
    "type": "client_credentials",
    "tenant_id": "${azure.tenant.id}",
    "client_id": "${sharepoint.client.id}",
    "client_secret": "${sharepoint.client.secret}"
  }
}
```

### Certificate Authentication

More secure for production environments.

```json
{
  "authentication": {
    "type": "certificate",
    "tenant_id": "${azure.tenant.id}",
    "client_id": "${sharepoint.client.id}",
    "certificate_path": "/path/to/cert.pem",
    "certificate_password": "${sharepoint.cert.password}"
  }
}
```

### Store Credentials Securely

Add to `application.properties`:

```properties
# Azure AD / SharePoint Configuration
azure.tenant.id=${AZURE_TENANT_ID}
sharepoint.client.id=${SHAREPOINT_CLIENT_ID}
sharepoint.client.secret=${SHAREPOINT_CLIENT_SECRET}
sharepoint.site.url=${SHAREPOINT_SITE_URL}
```

Set environment variables:
```bash
export AZURE_TENANT_ID="your-tenant-id"
export SHAREPOINT_CLIENT_ID="your-client-id"
export SHAREPOINT_CLIENT_SECRET="your-client-secret"
export SHAREPOINT_SITE_URL="https://tenant.sharepoint.com/sites/mysite"
```

---

## Security Best Practices

### 1. Principle of Least Privilege

Only request permissions your tool actually needs:

```json
{
  "options": {
    "allowed_operations": ["list_files", "search", "get_metadata"]
    // Don't include "delete", "upload" unless needed
  }
}
```

### 2. File Type Restrictions

Limit allowed file types:

```json
{
  "options": {
    "allowed_file_types": ["docx", "pdf", "xlsx", "pptx", "txt"],
    "max_file_size_mb": 50
  }
}
```

### 3. Audit Logging

Enable operation logging:

```json
{
  "options": {
    "audit_logging": true,
    "log_user_actions": true
  }
}
```

### 4. Token Management

- Use short-lived client secrets (6-12 months)
- Rotate secrets regularly
- Monitor for unauthorized access

---

## Examples

### Example 1: Project Document Manager

```json
{
  "name": "project_doc_manager",
  "description": "Manage project documents with version control",
  "tool_type": "documents",
  "version": "2.9.8",
  "site_url": "${sharepoint.site.url}",
  "authentication": {
    "type": "client_credentials",
    "tenant_id": "${azure.tenant.id}",
    "client_id": "${sharepoint.client.id}",
    "client_secret": "${sharepoint.client.secret}"
  },
  "options": {
    "default_folder": "/Shared Documents/Active Projects",
    "allowed_operations": [
      "list_files", "get_file", "download", "upload",
      "search", "get_metadata", "update_metadata",
      "get_versions", "check_out", "check_in"
    ],
    "enable_version_control": true,
    "max_file_size_mb": 100
  }
}
```

### Example 2: Task Tracker Integration

```json
{
  "name": "task_tracker",
  "description": "Sync tasks with SharePoint task list",
  "tool_type": "lists",
  "version": "2.9.8",
  "site_url": "${sharepoint.site.url}",
  "options": {
    "default_list": "Project Tasks",
    "allowed_operations": [
      "get_list_items", "get_item", "create_item",
      "update_item", "query_items"
    ]
  }
}
```

### Example 3: Enterprise Content Search

```json
{
  "name": "content_search",
  "description": "Search across all SharePoint content",
  "tool_type": "search",
  "version": "2.9.8",
  "site_url": "${sharepoint.site.url}",
  "options": {
    "search_types": ["all", "documents"],
    "max_results": 100,
    "highlight_results": true
  }
}
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| 401 Unauthorized | Invalid credentials | Verify tenant/client IDs and secret |
| 403 Forbidden | Missing permissions | Add required API permissions in Azure |
| Site not found | Wrong site URL | Verify site URL format |
| Token expired | Secret expired | Rotate client secret |
| CORS error | Browser blocking | Use server-side requests |

### Debug Configuration

```json
{
  "debug": {
    "log_requests": true,
    "log_responses": false,
    "trace_api_calls": true
  }
}
```

### Verify Azure AD Setup

```bash
# Test token acquisition
curl -X POST "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "client_id={client_id}" \
  -d "client_secret={client_secret}" \
  -d "scope=https://graph.microsoft.com/.default" \
  -d "grant_type=client_credentials"
```

### Test SharePoint API

```bash
# Test API access with token
curl -H "Authorization: Bearer {access_token}" \
  "https://{tenant}.sharepoint.com/sites/{site}/_api/web"
```

---

## Related Documentation

- [MCP Studio Overview](MCP_Studio_User_Guide.md)
- [Variable Substitution Guide](../architecture/SAJHA_MCP_Server_Architecture.md)
- [Microsoft Graph API Documentation](https://docs.microsoft.com/en-us/graph/)
- [SharePoint REST API Reference](https://docs.microsoft.com/en-us/sharepoint/dev/sp-add-ins/get-to-know-the-sharepoint-rest-service)

---

*SAJHA MCP Server v2.9.8 - SharePoint Tool Creator Guide*
*Copyright © 2025-2030 Ashutosh Sinha*
