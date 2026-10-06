# MCP Studio SharePoint Tool Creator Guide

The SharePoint Tool Creator builds MCP tools that work with a Microsoft SharePoint site: documents, lists, site information and search. You fill in a form and Studio produces a tool configuration. No Python file is generated, because every SharePoint tool runs on one of the classes already shipped in `sajha/tools/impl/sharepoint_tool.py`.

Where Studio lives, the common create → preview → deploy workflow, where generated files are stored, hot reload and permissions are covered once in the [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md).

## Contents

1. [Opening the creator](#opening-the-creator)
2. [Tool types](#tool-types)
3. [Form reference](#form-reference)
4. [Operations and arguments](#operations-and-arguments)
5. [Generated configuration](#generated-configuration)
6. [Credentials and variables](#credentials-and-variables)
7. [Azure AD app registration](#azure-ad-app-registration)
8. [Runtime notes](#runtime-notes)
9. [Troubleshooting](#troubleshooting)

---

## Opening the creator

The page is served at `/studio/sharepoint`. To reach it, use the **SharePoint** card on the Studio home page (`/studio`) or the **SharePoint** chip in the Studio sub-navigation. It has no entry in the top-bar **MCP Studio** menu.

---

## Tool types

Pick a type in **1. Select Tool Type**. Each type maps to a fixed implementation class:

| Type | Implementation class | Purpose |
|------|----------------------|---------|
| **Documents** | `sajha.tools.impl.sharepoint_tool.SharePointDocumentTool` | Files and folders |
| **Lists** | `sajha.tools.impl.sharepoint_tool.SharePointListTool` | Lists and list items |
| **Sites** | `sajha.tools.impl.sharepoint_tool.SharePointSiteTool` | Site information, users, groups, permissions |
| **Search** | `sajha.tools.impl.sharepoint_tool.SharePointSearchTool` | Search across content, people and sites |

---

## Form reference

### 2. Basic Information

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| Tool Name | Yes | none | Pattern `[a-z][a-z0-9_]*`. Also used as the config file name. |
| Version | No | Server version | The tool's own version string. It is written to the config as `version`. |
| Description | Yes | none | Shown to MCP clients. |
| Category | No | `Document Management` | |
| Tags | No | none | Comma-separated. The page sends an empty list when blank. The generator's default (`sharepoint, microsoft, documents`) applies only when the key is omitted, for example from Python. |

### 3. SharePoint Connection

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| SharePoint Site URL | Yes | none | For example `https://tenant.sharepoint.com/sites/mysite`, or a variable such as `${sharepoint.site.url}`. |
| Default Folder Path | No | `/Shared Documents` | |
| Default List Name | No | none | |

### 4. Azure AD Authentication

| Field | Required | Notes |
|-------|----------|-------|
| Authentication Type | No | The choices are `client_credentials` (the default), `certificate` and `user_credentials`. Only client credentials works at run time. See [Runtime notes](#runtime-notes). |
| Tenant ID | Yes | A GUID or `${azure.tenant.id}`. |
| Client ID | Yes | A GUID or `${sharepoint.client.id}`. |
| Client Secret | No | Prefer `${sharepoint.client.secret}`. The live preview masks a literal secret as `***hidden***`. |

### 5. Select Operations

The page shows a checkbox group for the selected tool type. The ticked operations become the `enum` of the `operation` argument in the generated input schema. When no operations are ticked, the generator allows every operation for that type.

The page submits every ticked checkbox, including those in the hidden groups for the other tool types, several of which are ticked by default. Check the `operation` enum in the generated file and remove values that do not belong to the tool's type.

### 6. Options

| Field | Default | Range |
|-------|---------|-------|
| Max File Size (MB) | 100 | 1–500 |
| Cache TTL (seconds) | 300 | 0–3600 |
| Allowed File Types | empty, which means all | Comma-separated, for example `docx,pdf,xlsx` |
| Enable Version Control | on | |
| Enable Metadata Operations | on | |
| Enable Caching | on | |

### Buttons

- **Preview Configuration**: refreshes the JSON preview panel and scrolls to it. The preview also updates as you type. The preview is a summary built in the browser. It is not the full file the generator writes.
- **Deploy Tool**: submits the form. See the note below.

> Deploy posts to `/admin/studio/sharepoint/deploy`, loads the tool at once and then opens the Tools list. `/admin/studio/sharepoint/preview` returns the generated config with the client secret masked. See [Action endpoints](MCP%20Studio%20User%20Guide.md#action-endpoints-deploy-load-and-delete).

---

## Operations and arguments

The argument names below are the ones the implementation classes read.

### Documents (`SharePointDocumentTool`)

| Operation | Arguments read |
|-----------|----------------|
| `list_files` | `folder_path` (defaults to `/Shared Documents`), `recursive` |
| `get_file` | `file_url` |
| `download` | `file_url`, `return_content` |
| `upload` | `folder_path`, `file_name`, `content_base64`, `overwrite` |
| `search` | `query`, `folder_path`, `file_types`, `max_results` |
| `get_metadata` | `file_url` |
| `update_metadata` | `file_url`, `metadata` |
| `check_out` | `file_url` |
| `check_in` | `file_url`, `comment`, `check_in_type` |
| `get_versions` | `file_url` |
| `delete` | `file_url`, `recycle` |
| `move` | `source_url`, `destination_url`, `overwrite` |
| `copy` | `source_url`, `destination_url`, `overwrite` |

The generated input schema for a Documents tool declares only `operation`, `folder_path`, `file_url`, `file_name`, `query`, `metadata` and `destination_url`. To advertise the other arguments to clients (`recursive`, `content_base64`, `source_url` and so on), add them to `inputSchema` by hand.

### Lists (`SharePointListTool`)

| Operation | Arguments read |
|-----------|----------------|
| `get_lists` | none |
| `get_list_items` | `list_name`, `top`, `skip`, `select_fields`, `order_by` |
| `get_item` | `list_name`, `item_id` |
| `create_item` | `list_name`, `item_data` |
| `update_item` | `list_name`, `item_id`, `item_data` |
| `delete_item` | `list_name`, `item_id`, `recycle` |
| `get_list_schema` | `list_name` |
| `query_items` | `list_name`, `filter` (OData), `select_fields`, `order_by`, `top` |

### Sites (`SharePointSiteTool`)

| Operation | Arguments read |
|-----------|----------------|
| `get_site_info` | none |
| `get_subsites` | none |
| `get_users` | none |
| `get_groups` | none |
| `get_permissions` | `object_url` |
| `get_content_types` | none |

### Search (`SharePointSearchTool`)

Search tools take `search_type` instead of `operation`. The values are `all`, `documents`, `people` and `sites`, and the default is `all`. They also read `query`, `max_results`, `start_row` (with `all`), and `file_types` and `folder_path` (with `documents`).

Example calls:

```json
{ "operation": "list_files", "folder_path": "/Shared Documents/Projects" }
```

```json
{ "operation": "query_items", "list_name": "Projects",
  "filter": "Status eq 'Active'", "select_fields": ["Title", "Status"] }
```

```json
{ "query": "quarterly report", "search_type": "documents", "file_types": ["pdf", "docx"], "max_results": 20 }
```

---

## Generated configuration

`SharePointToolGenerator` writes one file, `config/tools/<tool_name>.json`, through the configured storage backend. It does not write a Python file. Here is the output for a Documents tool with five operations ticked:

```json
{
  "name": "sharepoint_project_docs",
  "description": "Read project documents in SharePoint",
  "category": "Document Management",
  "version": "1.0.0",
  "enabled": true,
  "implementation": "sajha.tools.impl.sharepoint_tool.SharePointDocumentTool",
  "site_url": "${sharepoint.site.url}",
  "authentication": {
    "type": "client_credentials",
    "tenant_id": "${azure.tenant.id}",
    "client_id": "${sharepoint.client.id}",
    "client_secret": "${sharepoint.client.secret}"
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "operation": {
        "type": "string",
        "enum": ["list_files", "get_file", "download", "search", "get_metadata"],
        "description": "Operation to perform"
      },
      "folder_path": {"type": "string", "description": "Folder path"},
      "file_url": {"type": "string", "description": "File URL"},
      "file_name": {"type": "string", "description": "File name"},
      "query": {"type": "string", "description": "Search query"},
      "metadata": {"type": "object", "description": "Metadata fields"},
      "destination_url": {"type": "string", "description": "Destination for move/copy"}
    },
    "required": ["operation"]
  },
  "outputSchema": {
    "type": "object",
    "properties": {
      "success": {"type": "boolean"},
      "data": {"type": "object"},
      "results": {"type": "array"},
      "execution_time_ms": {"type": "number"},
      "error": {"type": "string"}
    }
  },
  "options": {
    "default_folder": "/Shared Documents/Projects",
    "default_list": "",
    "max_file_size_mb": 100,
    "allowed_file_types": ["docx", "pdf"],
    "enable_version_control": true,
    "enable_metadata": true
  },
  "caching": {"enabled": true, "ttl_seconds": 300},
  "metadata": {
    "author": "MCP Studio",
    "category": "Document Management",
    "tags": ["sharepoint", "projects"],
    "tool_type": "documents",
    "generator_version": "2.9.8"
  }
}
```

`metadata.generator_version` is a fixed string that the generator stamps on every file. It does not describe the server release.

Examples ship in `config/tools/`: `sharepoint_documents.json`, `sharepoint_lists.json` and `sharepoint_search.json`.

From Python, without the page:

```python
from sajha.studio.sharepoint_tool_generator import SharePointToolGenerator

gen = SharePointToolGenerator()               # output_dir defaults to config/tools
cfg = SharePointToolGenerator.from_dict({
    "name": "sharepoint_project_docs",
    "description": "Read project documents in SharePoint",
    "tool_type": "documents",
    "site_url": "${sharepoint.site.url}",
    "tenant_id": "${azure.tenant.id}",
    "client_id": "${sharepoint.client.id}",
    "client_secret": "${sharepoint.client.secret}",
    "allowed_operations": ["list_files", "get_file", "download", "search", "get_metadata"],
})
errors = gen.validate(cfg)                    # [] when valid
if not errors:
    gen.save(cfg)
```

`validate()` checks four things: the name is alphanumeric with underscores, the description is set, the tool type is one of the four, and the site URL is set.

---

## Credentials and variables

When the tools registry loads a config, it resolves every `${key}` placeholder against `config/application.yml`, using dotted paths into the YAML. An environment variable named exactly like the dotted key overrides the file value. A YAML value can itself read an environment variable with `${ENV_VAR:default}`. To keep secrets out of tool JSON, add a block like this:

```yaml
azure:
  tenant:
    id: ${AZURE_TENANT_ID:}
sharepoint:
  site:
    url: ${SHAREPOINT_SITE_URL:}
  client:
    id: ${SHAREPOINT_CLIENT_ID:}
    secret: ${SHAREPOINT_CLIENT_SECRET:}
```

The page's side panel lists the four variable names used above: `${sharepoint.site.url}`, `${azure.tenant.id}`, `${sharepoint.client.id}` and `${sharepoint.client.secret}`.

---

## Azure AD app registration

The page's setup panel lists these steps:

1. In the Azure Portal, open **Azure AD → App registrations** and create a new registration.
2. Add API permissions. The page suggests **SharePoint → Sites.Read.All**. Add write permissions only if you enable write operations such as `upload`, `create_item` or `delete`.
3. Create a client secret and copy it. It is shown only once.
4. Copy the tenant ID, client ID and secret into the variables above.

---

## Runtime notes

These notes come from `sajha/tools/impl/sharepoint_tool.py`:

- Requests go to Microsoft Graph (`https://graph.microsoft.com/v1.0`), the API the
  client-credentials token (scope `https://graph.microsoft.com/.default`) is valid for. What
  each operation calls, and the Graph permissions the app needs, are in the
  [SharePoint Tool Reference Guide](../tools/enterprise/SharePoint%20Tool%20Reference%20Guide.md).
- Only `client_credentials` is implemented (read from `authentication.type`); any other type
  answers with an error saying so.
- The `operation` enum is enforced: the server validates every call against the input schema.
- The `options` and `caching` blocks are stored in the config, but the current SharePoint classes do not enforce them. That covers `max_file_size_mb`, `allowed_file_types`, the version-control and metadata switches, and the cache TTL. What limits which operations a client sees is the `operation` enum in the input schema.

---

## Troubleshooting

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| Deploy shows an error | The name is taken or invalid, or a required field is missing | The alert gives the validation message. Fix the field, or delete the existing Studio tool first. |
| `Tenant ID required for client credentials auth` | Validation failed | Set Tenant ID and Client ID, or use their variables. |
| `Unsupported SharePoint authentication type` | A non-client-credentials auth type was chosen | Use client credentials. |
| `Microsoft Graph ... failed: HTTP 401` or `403` | Token or permissions problem | Check the tenant, client ID, secret and the Graph application permissions (`Sites.Read.All` / `Sites.ReadWrite.All`). |
| `SharePoint is not configured: ...` | The site URL or credentials are empty | Set `SHAREPOINT_SITE_URL`, `AZURE_TENANT_ID`, `SHAREPOINT_CLIENT_ID`, `SHAREPOINT_CLIENT_SECRET` (read by `sharepoint.*` / `azure.tenant.id` in `config/application.yml`). |

Token check outside SAJHA:

```bash
curl -X POST "https://login.microsoftonline.com/<tenant_id>/oauth2/v2.0/token" \
  -d "client_id=<client_id>" -d "client_secret=<client_secret>" \
  -d "scope=https://graph.microsoft.com/.default" -d "grant_type=client_credentials"
```

---

## Related documentation

- [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md)
- [Storage Guide](../getting-started/Storage%20Guide.md): where `config/tools/` is written under the s3, azure and gcs backends
- [Architecture](../architecture/Architecture.md)
- [Glossary](../../GLOSSARY.md)
- [SharePoint REST service](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/get-to-know-the-sharepoint-rest-service)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
