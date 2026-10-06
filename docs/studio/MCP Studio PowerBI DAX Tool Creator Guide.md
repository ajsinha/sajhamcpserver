# MCP Studio PowerBI DAX Query Tool Creator Guide

Where Studio lives, the common create → preview → deploy workflow, where generated files are stored, hot reload and permissions are covered once in the [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md).

The PowerBI DAX Query Tool Creator (`/studio/powerbidax`) builds an MCP tool that runs **one DAX query template** against a PowerBI dataset and returns the rows as JSON. To export a whole report as PDF, PPTX or PNG instead, see the [PowerBI Report Tool Creator Guide](MCP%20Studio%20PowerBI%20Tool%20Creator%20Guide.md).

---

## Prerequisites

- An Azure AD (Entra ID) app registration (service principal) with access to the dataset's workspace.
- The **Workspace ID** and **Dataset ID** as GUIDs.
- The client secret in the server environment variable `POWERBI_CLIENT_SECRET`. This page has no field to change that name. The generator defaults to it.
- A DAX query that runs in PowerBI Desktop's DAX query view. The tool calls the PowerBI REST `executeQueries` API, which has its own tenant settings and limits. See Microsoft's documentation.

---

## Form Fields

### Basic Information

| Field | Required | Notes |
|-------|----------|-------|
| Tool Name | Yes | Letters, digits and underscores. It must not start with a digit. |
| Description | Yes | The tool description that MCP clients see. |
| Dataset Name | Yes | A human-readable dataset name. It is returned in every result. |
| Tags | No | A comma-separated list. If you leave it empty, the generator uses its own default tags. |
| Author | No | If you leave it empty, the metadata author is set to `MCP Studio - PowerBI DAX Generator`. |

### PowerBI Connection

| Field | Required | Notes |
|-------|----------|-------|
| Workspace ID | Yes | Must be a GUID. |
| Dataset ID | Yes | Must be a GUID. |
| Tenant ID | Yes | Must be a GUID. |
| Client ID | Yes | Must be a GUID. |

### DAX Query

| Field | Required | Notes |
|-------|----------|-------|
| DAX Query | Yes | Must start with `EVALUATE`. Use `@name` for parameters. |
| Query Parameters | No | Add rows with **Add Parameter**. Each row has a name, a type (`string`, `integer` or `number`) and a description. Every parameter you add is **required**. |
| Timeout (seconds) | No | Default 60. The page allows 10–300. |
| Max Rows | No | Default 10000. The page allows 100–100000. |

The **Live Preview** panel shows the config as you type. **Preview** and **Deploy Tool** call `POST /admin/studio/powerbidax/preview` and `POST /admin/studio/powerbidax/deploy`. A successful deploy loads the tool at once; see [Action endpoints](MCP%20Studio%20User%20Guide.md#action-endpoints-deploy-load-and-delete).

---

## Parameters

Each parameter becomes a property of the tool's input schema, with the type and description you set. If you define no parameters, the schema has a single optional `parameters` object instead.

When the tool runs, every argument that is not null replaces each `@name` in the query:

- **String** values are wrapped in double quotes, and any `"` inside them is doubled. Write `@region`, **not** `"@region"`.
- **Integer** and **number** values are inserted as they are.

```dax
EVALUATE
FILTER(
    SUMMARIZECOLUMNS('Product'[Category], 'Date'[Year], "Sales", SUM(Sales[Amount])),
    'Date'[Year] = @year && 'Product'[Category] = @category
)
```

With the parameters `year` (integer) and `category` (string), a call with `{"year": 2025, "category": "Bikes"}` runs a query that ends in `'Date'[Year] = 2025 && 'Product'[Category] = "Bikes"`.

Substitution is plain text replacement. Avoid parameter names that are prefixes of other parameter names, such as `@year` and `@year_end`.

---

## What Gets Generated

`PowerBIDAXToolGenerator` (`sajha/studio/powerbidax_tool_generator.py`) writes these files:

| File | Name |
|------|------|
| Tool config | `config/tools/<tool_name>.json` |
| Implementation | `sajha/tools/impl/powerbidax_<tool_name>.py`, which contains the class `PowerBIDAX<ToolName>Tool` |

The tool config looks like this. The generator also writes `version`.

```json
{
  "name": "sales_by_category",
  "implementation": "sajha.tools.impl.powerbidax_sales_by_category.PowerBIDAXSalesByCategoryTool",
  "description": "Sales by product category for a year",
  "enabled": true,
  "metadata": {
    "author": "MCP Studio - PowerBI DAX Generator",
    "category": "PowerBI",
    "tags": ["powerbi", "dax"],
    "rateLimit": 30,
    "cacheTTL": 60,
    "requiresApiKey": false,
    "source": "powerbi_dax",
    "dataset_name": "Sales Analytics"
  }
}
```

The query, IDs, timeout and max rows are baked into the generated Python class. To change any of them, regenerate the tool.

---

## Runtime Behaviour

1. The tool gets a client-credentials token from Azure AD with scope `https://analysis.windows.net/powerbi/api/.default`.
2. It substitutes the parameters and calls `POST https://api.powerbi.com/v1.0/myorg/groups/<workspace>/datasets/<dataset>/executeQueries`, with `includeNulls` set to true.
3. It returns the first result table.

| Output field | Description |
|--------------|-------------|
| `success` | Whether the query succeeded. |
| `dataset_name` | The configured dataset name. |
| `row_count` | The number of rows the API returned, counted before the Max Rows cap. |
| `columns` | The column names. |
| `data` | The rows, as objects. At most Max Rows are returned. |
| `query_time_seconds` | How long the query took. |
| `error` | The error message when `success` is false. PowerBI's own error text is included when it is available. |

---

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| Authentication fails | `POWERBI_CLIENT_SECRET` is not set on the server, or the tenant ID, client ID or secret is wrong. |
| 401 or 403 from `executeQueries` | The service principal has no dataset access, or the tenant setting that allows the API is off. |
| `DAX query must start with EVALUATE` | Validation rejected the query. Start it with `EVALUATE`. |
| A column or table is not found | The names do not match the dataset model. Test the query in PowerBI Desktop first. |
| Literal `@name` text is left in the query | The caller did not supply that argument, or the argument was null. |
| Quoting errors on a string parameter | The template has quotes around `@name`. Remove them, because the tool adds them. |

---

## Related Documentation

- [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md)
- [PowerBI Report Tool Creator Guide](MCP%20Studio%20PowerBI%20Tool%20Creator%20Guide.md)
- [OLAP Tool Creator Guide](MCP%20Studio%20OLAP%20Tool%20Creator%20Guide.md)
- [Glossary](../../GLOSSARY.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
