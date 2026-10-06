# MCP Studio IBM LiveLink Tool Creator Guide

Where Studio lives, the common create → preview → deploy workflow, where generated files are stored, hot reload and permissions are covered once in the [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md).

The IBM LiveLink Document Tool Creator (`/studio/livelink`) builds an MCP tool for an OpenText Content Server (LiveLink) instance. The tool can search for documents, list a folder, get a node's metadata, and download a document as base64. It talks to the server's REST API at `<server_url>/api/<v1|v2>/...`.

---

## Prerequisites

- The Content Server URL, for example `https://livelink.company.com/otcs/cs.exe`.
- REST API access enabled on the server.
- Credentials in **environment variables** on the SAJHA server. The generated tool reads them when it runs and never stores them in the tool config.

---

## Form Fields

### Basic Information

| Field | Required | Notes |
|-------|----------|-------|
| Tool Name | Yes | Letters, digits and underscores. It must not start with a digit. |
| Description | Yes | The tool description that MCP clients see. |
| Tags | No | A comma-separated list. If you leave it empty, the generator uses its own default tags. |
| Author | No | If you leave it empty, the metadata author is set to `MCP Studio - LiveLink Generator`. |

### Server Configuration

| Field | Required | Notes |
|-------|----------|-------|
| Server URL | Yes | Must start with `http://` or `https://`. A trailing `/` is removed. |
| API Version | No | `v2` (the default) or `v1`. |
| Default Parent Folder ID | No | The folder node that the `list` action uses when the caller does not pass `parent_id`. |

### Authentication

| Type | Environment variables (the defaults are editable) | How it authenticates |
|------|---------------------------------------------------|----------------------|
| `basic` (default) | `LIVELINK_USERNAME`, `LIVELINK_PASSWORD` | Sends an HTTP `Authorization: Basic` header on every request. |
| `otds` | `LIVELINK_USERNAME`, `LIVELINK_PASSWORD` | Posts the credentials to `<server_url>/api/<version>/auth`, then sends the returned ticket as an `OTCSTicket` header. The ticket is cached for about an hour. |
| `oauth` | `LIVELINK_OAUTH_TOKEN` | Sends `Authorization: Bearer <token>`. You must supply and refresh the token yourself; the tool does not fetch it. |

### Request Options

| Field | Default | Range |
|-------|---------|-------|
| Timeout (seconds) | 60 | 10–300 |
| Max File Size (MB) | 50 | 1–500. Larger downloads are refused. |

The **Live Preview** panel shows the config as you type. **Preview** and **Deploy Tool** call `POST /admin/studio/livelink/preview` and `POST /admin/studio/livelink/deploy`. A successful deploy loads the tool at once; see [Action endpoints](MCP%20Studio%20User%20Guide.md#action-endpoints-deploy-load-and-delete).

---

## What Gets Generated

`LiveLinkToolGenerator` (`sajha/studio/livelink_tool_generator.py`) writes these files:

| File | Name |
|------|------|
| Tool config | `config/tools/<tool_name>.json` |
| Implementation | `sajha/tools/impl/livelink_<tool_name>.py`, which contains the class `LiveLink<ToolName>Tool` |

The tool config looks like this. The generator also writes `version`.

```json
{
  "name": "company_docs",
  "implementation": "sajha.tools.impl.livelink_company_docs.LiveLinkCompanyDocsTool",
  "description": "Search and download company documents",
  "enabled": true,
  "metadata": {
    "author": "MCP Studio - LiveLink Generator",
    "category": "Document Management",
    "tags": ["livelink", "document"],
    "rateLimit": 20,
    "cacheTTL": 0,
    "requiresApiKey": false,
    "source": "livelink",
    "auth_type": "basic",
    "api_version": "v2"
  }
}
```

The server URL, auth type, environment variable names, default folder, timeout and size limit are baked into the generated Python class. To change any of them, regenerate the tool.

---

## Runtime Behaviour

### Input schema

All inputs are optional. `action` defaults to `search`.

| Argument | Type | Used by | Description |
|----------|------|---------|-------------|
| `action` | string | all | One of `search`, `get`, `download` or `list`. |
| `query` | string | `search` | Finds documents whose name contains this text. |
| `document_name` | string | `search` | Matches on name. Used only when `query` is empty. |
| `document_id` | string | `get`, `download` | The node ID. |
| `parent_id` | string | `list` | The folder node ID. If omitted, the Default Parent Folder ID is used. |
| `max_results` | integer | `search`, `list` | Default 25, from 1 to 100. |

### Actions

| Action | REST call | Returns |
|--------|-----------|---------|
| `search` | `GET nodes`, limited to documents (`where_type=144`) | `results` and `result_count` |
| `list` | `GET nodes/<parent_id>/nodes` | `results` and `result_count` |
| `get` | `GET nodes/<document_id>` | `metadata` |
| `download` | `GET nodes/<document_id>/content` | `data` (base64), `mime_type`, `size_bytes` and `document_name` |

Every response includes `success` and `action`. When something goes wrong it also includes `error`. Documents are never cached: the generated config sets `cacheTTL` to 0.

---

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `Authentication failed - check credentials` | The environment variables for the selected auth type are not set on the server. |
| 401 with `otds` | The username or password is wrong, or the server's `/api/<version>/auth` endpoint rejected the login. |
| 401 with `oauth` | The token in `LIVELINK_OAUTH_TOKEN` has expired. Refresh it outside SAJHA. |
| `Parent folder ID is required` | `list` was called with no `parent_id`, and no default folder is configured. |
| A download is refused as too large | The file is bigger than Max File Size. Regenerate the tool with a higher limit (up to 500 MB). |
| 404 on every call | The Server URL or API version is wrong. Check `<server_url>/api/v1/...` against `v2`. |

---

## Related Documentation

- [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md)
- [SharePoint Tool Creator Guide](MCP%20Studio%20SharePoint%20Tool%20Creator%20Guide.md)
- [Glossary](../../GLOSSARY.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
