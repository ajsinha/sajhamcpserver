# MCP Studio PowerBI Report Tool Creator Guide

Where Studio lives, the common create → preview → deploy workflow, where generated files are stored, hot reload and permissions are covered once in the [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md).

The PowerBI Report Tool Creator (`/studio/powerbi`) builds an MCP tool that exports **one PowerBI report** as PDF, PPTX or PNG and returns the file base64-encoded. It does not run DAX queries. For that, use the [PowerBI DAX Query Tool Creator](MCP%20Studio%20PowerBI%20DAX%20Tool%20Creator%20Guide.md).

---

## Prerequisites

- An Azure AD (Entra ID) app registration (service principal) with access to the PowerBI workspace that holds the report.
- The report's **Workspace ID** and **Report ID**. Both are GUIDs, and you can read them from the report URL: `https://app.powerbi.com/groups/<workspace-id>/reports/<report-id>/...`.
- The client secret must be in an **environment variable** on the SAJHA server. The generated tool reads the secret from the environment and never stores it in the tool config.
- Export uses the PowerBI REST `ExportTo` API, which needs capacity that supports report export (Premium, Embedded or Fabric). Check this against Microsoft's documentation for your tenant.

---

## Form Fields

### Basic Information

| Field | Required | Notes |
|-------|----------|-------|
| Tool Name | Yes | Letters, digits and underscores. It must not start with a digit. |
| Description | Yes | The tool description that MCP clients see. |
| Report Display Name | Yes | A human-readable report name. It goes into the tool description, metadata and output. |
| Category | No | Defaults to `PowerBI Reports`. The page sends it, but the generator does not use it: the generated config always has `metadata.category` set to `PowerBI`. |
| Tags | No | A comma-separated list. If you leave it empty, the generator uses its own default tags. |

### Report Configuration

| Field | Required | Notes |
|-------|----------|-------|
| Workspace ID (Group ID) | Yes | Must be a GUID. |
| Report ID | Yes | Must be a GUID. |
| Page Name | No | Leave it empty to export all pages. Callers can also pass `page_name` when they call the tool. |
| Export Format | No | `PDF` (the default), `PPTX` or `PNG`. The format is fixed when the tool is generated. |

### Azure AD Authentication

| Field | Required | Notes |
|-------|----------|-------|
| Tenant ID | Yes | Must be a GUID. |
| Client ID (Application ID) | Yes | Must be a GUID. |
| Client Secret Environment Variable | No | Defaults to `POWERBI_CLIENT_SECRET`. This is the name of the variable, not the secret itself. |

### Advanced

| Field | Default | Range |
|-------|---------|-------|
| Timeout (seconds) | 120 | 30–600 |
| Author | (none) | If you leave it empty, the metadata author is set to `MCP Studio - PowerBI Generator`. |

The right-hand **Live Preview** panel shows the JSON configuration as you type. **Preview Configuration** and **Deploy Tool** send the form to `POST /admin/studio/powerbi/preview` and `POST /admin/studio/powerbi/deploy`. See [Known limitation: Studio action endpoints](MCP%20Studio%20User%20Guide.md#known-limitation-studio-action-endpoints): these endpoints are not registered in this release.

---

## What Gets Generated

`PowerBIToolGenerator` (`sajha/studio/powerbi_tool_generator.py`) writes these files:

| File | Name |
|------|------|
| Tool config | `config/tools/<tool_name>.json` |
| Implementation | `sajha/tools/impl/powerbi_<tool_name>.py`, which contains the class `PowerBI<ToolName>Tool` |

The tool config looks like this. The generator also writes `version`.

```json
{
  "name": "sales_report_pdf",
  "implementation": "sajha.tools.impl.powerbi_sales_report_pdf.PowerBISalesReportPdfTool",
  "description": "Retrieve the monthly sales report as PDF",
  "enabled": true,
  "metadata": {
    "author": "MCP Studio - PowerBI Generator",
    "category": "PowerBI",
    "tags": ["powerbi", "report", "pdf"],
    "rateLimit": 10,
    "cacheTTL": 300,
    "requiresApiKey": false,
    "source": "powerbi",
    "report_name": "Monthly Sales Report",
    "export_format": "PDF"
  }
}
```

The workspace ID, report ID, tenant ID, client ID, secret variable name, page and timeout are baked into the generated Python class as constants. To change any of them, regenerate the tool.

---

## Runtime Behaviour

### Input schema

All inputs are optional:

| Argument | Type | Description |
|----------|------|-------------|
| `report_name` | string | Overrides the report name, for logging only. |
| `page_name` | string | The page to export. If omitted, the configured page is used, or all pages if none was configured. |
| `filters` | object | Report-level filters. These are passed to the export request as `reportLevelFilters`. |

### Output

| Field | Description |
|-------|-------------|
| `success` | Whether the export succeeded. |
| `report_name` | The report name. |
| `format` | `PDF`, `PPTX` or `PNG`. |
| `data` | The file content, base64-encoded. |
| `size_bytes` | The size of the exported file. |
| `export_time_seconds` | How long the export took. |
| `error` | The error message when `success` is false. |

### How the export works

1. The tool gets a client-credentials token from `https://login.microsoftonline.com/<tenant>/oauth2/v2.0/token` with scope `https://analysis.windows.net/powerbi/api/.default`. The token is cached until shortly before it expires.
2. It calls `POST https://api.powerbi.com/v1.0/myorg/groups/<workspace>/reports/<report>/ExportTo`.
3. It polls the export status every 5 seconds, until the export succeeds, fails, or the configured timeout runs out.
4. It downloads the file and base64-encodes it.

The caller must decode `data` to get the file.

---

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| `Failed to authenticate with Azure AD` | The secret environment variable is not set on the server, or the tenant ID, client ID or secret is wrong. |
| 401 or 403 from the PowerBI API | The service principal has no access to the workspace, or service principals are not allowed in the tenant settings. |
| The export times out | The report is large or the capacity is busy. Raise the timeout (up to 600 s) or export a single page. |
| Validation error on a GUID field | The workspace, report, tenant or client ID is not in GUID form. |

To check API access by hand, run:

```bash
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://api.powerbi.com/v1.0/myorg/groups"
```

---

## Related Documentation

- [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md)
- [PowerBI DAX Query Tool Creator Guide](MCP%20Studio%20PowerBI%20DAX%20Tool%20Creator%20Guide.md)
- [Storage Guide](../getting-started/Storage%20Guide.md)
- [Glossary](../../GLOSSARY.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
