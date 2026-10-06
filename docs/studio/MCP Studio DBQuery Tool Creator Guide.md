# MCP Studio Database Query Tool Creator Guide

The Database Query Tool Creator (`/studio/dbquery`) turns a SQL query template into an MCP tool. You fill in a form; Studio generates a tool config plus a Python implementation that connects to the database, substitutes the caller's arguments into the query and returns the rows.

Where Studio lives, the common create → preview → deploy workflow, where generated files are stored, hot reload and permissions are covered once in the [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md).

---

## Supported databases

The generator accepts exactly these `db_type` values. Any other value fails validation.

| Database | `db_type` | Driver used by generated code | Connection string format |
|----------|-----------|-------------------------------|--------------------------|
| DuckDB | `duckdb` | `duckdb` | File path, e.g. `data/mydata.db`, or `:memory:` |
| SQLite | `sqlite` | `sqlite3` (standard library) | File path, e.g. `data/app.sqlite` |
| PostgreSQL | `postgresql` | `psycopg2` | libpq string passed to `psycopg2.connect()`, e.g. `host=localhost dbname=mydb user=postgres password=secret` |
| MySQL | `mysql` | `pymysql` | Semicolon-separated `key=value` pairs: `host=localhost;database=mydb;user=root;password=secret` |

The generated tool imports the driver when it runs. Install `psycopg2` or `pymysql` yourself if you use PostgreSQL or MySQL. For MySQL, the generated code reads only `host`, `database`, `user` and `password` from the string, so there is no port or SSL setting.

---

## Form fields

### Tool information

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| Tool Name | Yes | – | Must start with a lowercase letter. Use lowercase letters, digits and underscores, at least 3 characters. Becomes the tool name and the file names. |
| Category | No | `Database` | Stored in `metadata.category`. |
| Description | Yes | – | The tool description that clients see. |
| Literature / Context (for AI) | No | – | Free-text context: business rules, a data dictionary, usage notes. The first 500 characters are stored in `metadata.literature` and in the generated class docstring. |

### Database connection

| Field | Required | Default | Notes |
|-------|----------|---------|-------|
| Database Type | Yes | DuckDB | One of the four buttons above. |
| Connection String | Yes | – | See the format table above. It is written verbatim into the generated Python file, so read [Security notes](#security-notes) before you put credentials here. |
| Timeout (seconds) | No | 30 | The form allows 1–300. The value is stored on the generated class, but the generated query code does not currently enforce it. |
| Max Rows | No | 1000 | The form allows 1–100000. The generated code calls `fetchmany(max_rows)`, so results are cut off at this many rows. |

### Query parameters

Click **Add Parameter** for each input. Each row has these fields:

| Field | Notes |
|-------|-------|
| Name | Must match a `{{name}}` placeholder in the query. Names must be unique. |
| Type | `string`, `integer`, `float`, `boolean`, `date` or `datetime` |
| Description | Defaults to `Parameter: <name>` if left blank. |
| Default | Optional. A parameter with a default is never listed as required in the schema. |
| Required | Checkbox. |
| Enum values | Optional comma-separated list. It becomes a JSON Schema `enum` and is checked at runtime. |

Types map to JSON Schema like this:

| Type | JSON Schema |
|------|-------------|
| `string` | `string` |
| `integer` | `integer` (the value is converted with `int()` at runtime) |
| `float` | `number` (the value is converted with `float()` at runtime) |
| `boolean` | `boolean` (strings `true`, `1` and `yes` count as true) |
| `date` | `string` with `format: date` |
| `datetime` | `string` with `format: date-time` |

### SQL query template

Write the query with `{{param_name}}` placeholders:

```sql
SELECT * FROM sales
WHERE region = {{region}}
  AND sale_date >= {{start_date}}
  AND sale_date <= {{end_date}}
ORDER BY sale_date DESC
```

Do not put quotes around placeholders. At runtime, the generated `_build_query()` method replaces each placeholder as follows:

- A **string** value is wrapped in single quotes, and any single quotes inside it are doubled (`'` becomes `''`).
- A **boolean** becomes `TRUE` or `FALSE`.
- **`None`** becomes `NULL`.
- **Anything else**, such as a number, is inserted with `str(value)`.

Validation fails in these cases:
- a placeholder has no matching parameter
- the template contains `DROP `, `DELETE ` or `TRUNCATE ` (in any case)

No other statement types are blocked.

### Quick examples

The sidebar has four examples you can click to load into the form: **Sales by Region** (DuckDB), **User Search** (SQLite), **Inventory Status** (PostgreSQL) and **Sales Aggregation** (DuckDB).

### Preview and Deploy

**Preview** shows the generated JSON, the Python implementation and the input and output schemas in tabs. **Deploy** becomes available after a successful preview. Both buttons send POST requests to `/admin/studio/dbquery/preview` and `/admin/studio/dbquery/deploy`. A successful deploy loads the tool at once; see [Action endpoints](MCP%20Studio%20User%20Guide.md#action-endpoints-deploy-load-and-delete).

---

## Generated files

| File | Name |
|------|------|
| Tool config | `config/tools/<tool_name>.json` |
| Implementation | `sajha/tools/impl/dbquery_<tool_name>.py`, class `DBQuery<ToolName>Tool` |

A save is refused if either file already exists, unless overwrite is requested.

Example config (`version` comes from the generator's `DBQueryToolDefinition.version` default):

```json
{
  "name": "get_sales_by_region",
  "implementation": "sajha.tools.impl.dbquery_get_sales_by_region.DBQueryGetSalesByRegionTool",
  "description": "Sales rows for a region and date range",
  "version": "2.9.8",
  "enabled": true,
  "metadata": {
    "author": "MCP Studio - DB Query Generator",
    "category": "Database",
    "tags": ["database", "query", "sql", "generated"],
    "rateLimit": 60,
    "cacheTTL": 60,
    "requiresApiKey": false,
    "source": "db_query",
    "db_type": "duckdb",
    "literature": ""
  }
}
```

### Output shape

On success:

```json
{
  "success": true,
  "data": [{"region": "EMEA", "amount": 1200.5}],
  "columns": ["region", "amount"],
  "row_count": 1,
  "query_time_ms": 4.21,
  "db_type": "duckdb"
}
```

On failure: `{"success": false, "error": "Validation error: ..."}` or `{"success": false, "error": "Query execution error: ..."}`.

---

## Security notes

- **Values are inlined, not bound.** The generated tool builds a SQL string. It does not use driver bind parameters. Escaping quotes protects string values, and numeric and boolean types are converted before they are inserted. Even so, prefer read-only database accounts and narrow queries.
- **The DROP/DELETE/TRUNCATE check runs only when the tool is generated.** It looks at the template, not at runtime values, and it does not block `UPDATE`, `INSERT` or DDL other than `DROP`. Use a database account that has only `SELECT` rights.
- **The connection string is embedded in the generated `.py` file.** Anyone who can read `sajha/tools/impl/` can see its credentials. Prefer file-based DuckDB/SQLite databases, or accounts with minimal privileges.

---

## Troubleshooting

| Message | Cause |
|---------|-------|
| `Tool name must start with lowercase letter...` | The name has uppercase letters, hyphens or a leading digit. |
| `Query placeholder '{{x}}' has no matching parameter definition` | Add a parameter named `x`, or remove the placeholder. |
| `Query contains potentially dangerous operations` | The template contains `DROP `, `DELETE ` or `TRUNCATE `. |
| `Required parameter 'x' is missing` (at runtime) | The caller left out a required parameter that has no default. |
| `Query execution error: No module named 'psycopg2'` / `'pymysql'` | Install the driver into the server's environment. |
| `Tool configuration already exists` | A tool with that name already exists. Choose another name. |

---

## Related documentation

- [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md)
- [SQL Select Tool Reference Guide](../tools/analytics/SQL%20Select%20Tool%20Reference%20Guide.md)
- [DuckDB Tool Reference Guide](../tools/analytics/DuckDB%20Tool%20Reference%20Guide.md)
- [Storage Guide](../getting-started/Storage%20Guide.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
