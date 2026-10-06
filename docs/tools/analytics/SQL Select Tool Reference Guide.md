# SQL Select Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Data Sources Configuration](#data-sources-configuration)
4. [Tools](#tools)
5. [Calling the Tools](#calling-the-tools)
6. [Security and Limitations](#security-and-limitations)
7. [Troubleshooting](#troubleshooting)

---

## Overview

The SQL Select tools (`sajha/tools/impl/sqlselect_tool_refactored.py`) run read-only `SELECT` queries over a catalog of named data sources (CSV, Parquet or JSON files) using an in-memory DuckDB connection. Unlike the [DuckDB tools](DuckDB%20Tool%20Reference%20Guide.md), which expose every file in a directory, SQL Select exposes only the sources declared in its configuration. No API key is required.

| Tool | Purpose |
|------|---------|
| `sqlselect_list_sources` | List configured data sources |
| `sqlselect_describe_source` | Columns, types, row count and metadata of a source |
| `sqlselect_get_schema` | Column schema of a source |
| `sqlselect_sample_data` | Preview rows from a source |
| `sqlselect_count_rows` | Count rows, optionally filtered |
| `sqlselect_execute_query` | Run a `SELECT` query across sources |

---

## Architecture

```
 MCP / REST call
       │
       ▼
 ┌────────────────────────────────────────┐
 │ sqlselect_* tools (SqlSelectBaseTool)  │
 │  • in-memory DuckDB connection         │
 │  • one view per configured source      │
 │  • SELECT-only validation, auto LIMIT  │
 └───────────────────┬────────────────────┘
                     ▼
 ┌────────────────────────────────────────┐
 │ <data.sqlselect.dir>/                  │
 │   customers.csv  orders.csv  ...       │
 └────────────────────────────────────────┘
```

When a tool is loaded it opens an in-memory DuckDB connection and creates a view named after each source (`read_csv_auto`, `read_parquet` or `read_json_auto`). Sources whose file is missing are skipped with a warning.

---

## Data Sources Configuration

Each `config/tools/sqlselect_*.json` carries the same `data_directory` and `data_sources` block:

```json
{
  "data_directory": "${data.sqlselect.dir:./data/sqlselect}",
  "data_sources": {
    "customers": {"file": "customers.csv", "type": "csv", "description": "Customer master data"},
    "orders":    {"file": "orders.csv",    "type": "csv", "description": "Order transactions"},
    "products":  {"file": "products.csv",  "type": "csv", "description": "Product catalog"},
    "sales":     {"file": "sales.csv",     "type": "csv", "description": "Sales data with customer and product details"}
  }
}
```

| Field | Description |
|-------|-------------|
| source key | View name used in SQL |
| `file` | File name relative to `data_directory` |
| `type` | `csv` (default), `parquet` or `json` |
| `description` | Free text shown by `sqlselect_list_sources` |

The data directory comes from `data.sqlselect.dir` in `config/application.yml` (default `./data/sqlselect`). Keep the `data_sources` block identical across the six tool configs, since each tool registers its own copy. See the [Configuration Reference](../../getting-started/Configuration%20Reference.md) and, for object-store deployments, the [Storage Guide](../../getting-started/Storage%20Guide.md).

---

## Tools

All responses include `success` and an ISO `timestamp`; failures return `{"success": false, "error": "..."}`.

### sqlselect_list_sources

No parameters. Returns `sources` (`name`, `file`, `type`, `description`) and `count`.

### sqlselect_describe_source

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source_name` | string | Yes | Source to describe |

Returns `source_name`, `file`, `type`, `description`, `row_count` and `columns` (`column_name`, `data_type`, `nullable`, `key`).

### sqlselect_get_schema

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source_name` | string | Yes | Source name |

Returns `source_name`, `schema` (`column_name`, `data_type`, `nullable`, `key`) and `column_count`.

### sqlselect_sample_data

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `source_name` | string | Yes | | Source name |
| `limit` | integer | No | 10 | 1–1000 |

Returns `source_name`, `columns`, `rows`, `row_count`.

### sqlselect_count_rows

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source_name` | string | Yes | Source name |
| `where_clause` | string | No | Filter condition without the `WHERE` keyword, e.g. `status = 'shipped'` |

Returns `source_name`, `row_count`, `where_clause`.

### sqlselect_execute_query

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | Yes | | A `SELECT` statement over the source views |
| `limit` | integer | No | 100 | 1–10000; appended as `LIMIT` when the query has none |

Returns `columns`, `rows`, `row_count` and the executed `query`.

```json
{
  "query": "SELECT c.customer_name, COUNT(o.order_id) AS orders FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_name ORDER BY orders DESC",
  "limit": 20
}
```

---

## Calling the Tools

Over MCP, send `tools/call` to `POST /mcp`:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "sqlselect_count_rows",
    "arguments": {"source_name": "orders", "where_clause": "quantity > 5"}
  }
}
```

Over REST, `POST /api/tools/execute` with `{"tool": "sqlselect_count_rows", "arguments": {...}}`; the response is `{"success": true, "result": {...}}`. Authenticate with `Authorization: Bearer <token>` or `X-API-Key: <key>`. See the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md) for protocol details.

---

## Security and Limitations

- **SELECT only.** `sqlselect_execute_query` requires the statement to start with `SELECT` (so `WITH ...` CTE queries are rejected) and rejects any query containing `DROP`, `DELETE`, `UPDATE`, `INSERT`, `CREATE`, `ALTER` or `TRUNCATE`, even inside identifiers or literals.
- **Row caps.** `limit` maxes out at 10,000 for queries and 1,000 for samples; everything is processed in memory.
- **Catalog scope.** Only configured sources are registered as views, but DuckDB file functions such as `read_csv_auto('<path>')` are not blocked, so restrict who may call `sqlselect_execute_query` via SAJHA roles/API-key scopes.
- **Trusted input.** `where_clause` and `source_name` are interpolated into SQL.
- **Concurrency.** Each tool instance has a single connection; data files are read at query time.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Source not found | Check `sqlselect_list_sources`; add the source to `data_sources` in every `sqlselect_*.json` |
| Source listed but queries fail with "table does not exist" | The file is missing from `data.sqlselect.dir`; check the server log warning |
| "Only SELECT queries are allowed" | Rewrite CTEs as subqueries; remove leading comments |
| "Query contains forbidden keyword" | Rename aliases/literals containing write keywords |
| Out of memory | Add filters, select fewer columns, lower `limit`, or convert large CSVs to Parquet |

See the [Glossary](../../../GLOSSARY.md) for SQL terms.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
