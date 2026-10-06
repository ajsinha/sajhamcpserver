# DuckDB Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Configuration](#configuration)
4. [Tools](#tools)
5. [Calling the Tools](#calling-the-tools)
6. [Limitations](#limitations)
7. [Troubleshooting](#troubleshooting)
8. [Appendix: Useful DuckDB SQL](#appendix-useful-duckdb-sql)

---

## Overview

The DuckDB tools run read-only SQL analytics over local CSV, TSV, Parquet and JSON files using the embedded DuckDB engine. There is no external API and no API key: everything runs against files in the configured data directory.

| Tool | Implementation | Purpose |
|------|----------------|---------|
| `duckdb_list_tables` | `duckdb_olap_tools_refactored.DuckDbListTablesTool` | List tables and views |
| `duckdb_describe_table` | `DuckDbDescribeTableTool` | Column schema, row count, optional sample rows |
| `duckdb_query` | `DuckDbQueryTool` | Run a read-only SQL query |
| `duckdb_get_stats` | `DuckDbGetStatsTool` | Column statistics and percentiles |
| `duckdb_aggregate` | `DuckDbAggregateTool` | Grouped aggregation without writing SQL |
| `duckdb_list_files` | `DuckDbListFilesTool` | List data files in the data directory |
| `duckdb_refresh_views` | `DuckDbRefreshViewsTool` | Re-validate views and reload changed files |
| `duckdb_sql` | `duckdb_olap_advanced.DuckDBSQLTool` | Lightweight SQL over `customers`, `orders`, `products` CSVs |

For semantic-layer pivots and time series over the same data, see the [OLAP Analytics Tool Reference Guide](OLAP%20Analytics%20Tool%20Reference%20Guide.md). For SQL over a separately configured set of sources, see the [SQL Select Tool Reference Guide](SQL%20Select%20Tool%20Reference%20Guide.md).

---

## Architecture

```
 MCP / REST call
       │
       ▼
 ┌─────────────────────────────────────────────┐
 │ duckdb_* tools (DuckDbBaseTool)             │
 │  • one DuckDB connection per tool instance  │
 │  • a view per data file, named after it     │
 │  • background auto-refresh of changed files │
 └──────────────────────┬──────────────────────┘
                        ▼
 ┌─────────────────────────────────────────────┐
 │ <data.duckdb.dir>/                          │
 │   *.csv  *.tsv  *.parquet *.pq *.json *.jsonl│
 │   duckdb_analytics.db                       │
 └─────────────────────────────────────────────┘
```

On start-up each `duckdb_*` tool scans the data directory and creates one view per file, using `read_csv_auto`, `read_parquet` or `read_json_auto`. The view name is the file name without extension, with non-alphanumeric characters replaced by `_` (so `sales-2024.csv` becomes `sales_2024`). Metadata is kept in `duckdb_analytics.db` in the same directory. When `auto_refresh_enabled` is true, a background thread re-scans every `auto_refresh_interval` seconds and recreates views for new or changed files.

`duckdb_sql` is separate: it opens an in-memory DuckDB connection and creates only the `customers`, `orders` and `products` views from the matching CSV files.

---

## Configuration

| Setting | Where | Default |
|---------|-------|---------|
| Data directory | `data.duckdb.dir` in `config/application.yml`, passed to each tool as `data_directory` | `./data/duckdb` |
| Auto refresh | `auto_refresh_enabled`, `auto_refresh_interval` (seconds) in a tool's `config/tools/duckdb_*.json` | enabled, 600 s (the shipped `duckdb_query.json` sets 300 s) |

No API keys are needed. See the [Configuration Reference](../../getting-started/Configuration%20Reference.md); for where data files live on S3/Azure/GCS deployments see the [Storage Guide](../../getting-started/Storage%20Guide.md).

---

## Tools

### duckdb_list_tables

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `include_system_tables` | boolean | No | false | Include system/internal tables |

Returns `tables` (each with `name`, `type`, `schema`, row count) and `total_count`.

### duckdb_describe_table

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `table_name` | string | Yes | | Table or view name |
| `include_sample_data` | boolean | No | false | Include sample rows |
| `sample_size` | integer | No | 5 | 1–100 |

Returns `table_name`, `table_type`, `columns` (`column_name`, `data_type`, `nullable`, `is_primary_key`, optional `default_value`), `row_count` and, if requested, `sample_data`.

### duckdb_query

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `sql_query` | string | Yes | | SQL to run |
| `limit` | integer | No | 100 | 1–10000; appended as `LIMIT` when the query has none |
| `output_format` | string | No | `json` | `json`, `csv`, `table` (accepted, but results are currently always returned as JSON rows) |

Queries containing `DROP`, `DELETE`, `TRUNCATE`, `ALTER`, `CREATE`, `INSERT` or `UPDATE` (anywhere in the text, case-insensitive) are rejected. Returns `query`, `columns`, `rows`, `row_count`, `execution_time_ms` and `limited` (true when the row cap was reached).

```json
{
  "sql_query": "SELECT c.customer_name, SUM(o.quantity * o.unit_price) AS total_spent FROM customers c JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.customer_name ORDER BY total_spent DESC",
  "limit": 10
}
```

Files can also be queried directly, e.g. `SELECT * FROM read_parquet('data/duckdb/events.parquet')`.

### duckdb_get_stats

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `table_name` | string | Yes | | Table to analyze |
| `columns` | array of string | No | all numeric columns | Columns to analyze |
| `include_percentiles` | boolean | No | true | Add `percentile_25`, `median`, `percentile_75` |

Returns `table_name`, `total_rows` and `column_statistics` keyed by column. Numeric columns get `count`, `null_count`, `min`, `max`, `unique_count`, `mean`, `std_dev`; non-numeric columns get the counts, `min` and `max`.

### duckdb_aggregate

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `table_name` | string | Yes | | Table to aggregate |
| `aggregations` | object | Yes | | `{"column": "function"}`; function is `sum`, `avg`, `count`, `min`, `max` or `count_distinct` |
| `group_by` | array of string | No | | Grouping columns |
| `having` | string | No | | HAVING condition on aggregate aliases |
| `order_by` | array of object | No | | `{"column": "...", "direction": "asc" \| "desc"}` |
| `limit` | integer | No | 100 | 1–10000 |

Each aggregate is aliased `<function>_<column>` (e.g. `sum_revenue`, `count_distinct_customer_id`); use those names in `having` and `order_by`. Returns `table_name`, `aggregations_applied`, `grouped_by`, `results`, `row_count`, `execution_time_ms`.

```json
{
  "table_name": "orders",
  "aggregations": {"quantity": "sum", "order_id": "count"},
  "group_by": ["region"],
  "having": "sum_quantity > 100",
  "order_by": [{"column": "sum_quantity", "direction": "desc"}]
}
```

### duckdb_list_files

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file_type` | string | No | `all` | `all`, `csv`, `parquet`, `json`, `tsv` |
| `include_metadata` | boolean | No | true | Include size and modification date |

Returns `data_directory`, `files` (`filename`, `file_type`, `file_path`, and with metadata `file_size_bytes`, `file_size_human`, `modified_date`), `total_files` and a `summary` of counts per type and total size.

### duckdb_refresh_views

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `view_name` | string | No | all views | View to refresh |
| `reload_external_files` | boolean | No | false | Re-scan the data directory and recreate views first |

Returns `refreshed_views` (`view_name`, `status`, `row_count`, `refresh_time_ms` or `error_message`), `total_refreshed` and `external_files_reloaded`.

### duckdb_sql

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `sql` | string | Yes | | Query over `customers`, `orders`, `products` |
| `limit` | integer | No | 100 | 1–1000 |

Only statements starting with `SELECT`, `WITH`, `EXPLAIN`, `DESCRIBE`, `SHOW` or `PRAGMA` are accepted. Returns `success`, `columns`, `data`, `row_count`, `sql`, `execution_time_ms`, `tables_available`.

`LIMIT <limit>` is appended to `SELECT`/`WITH` queries that have no `LIMIT` clause of their own; other statement types are run as written. A CSV file missing from the data directory leaves that view undefined (logged as a warning) instead of failing the tool.

---

## Calling the Tools

Over MCP, send `tools/call` to `POST /mcp`:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "duckdb_query",
    "arguments": {"sql_query": "SELECT region, COUNT(*) AS n FROM orders GROUP BY region"}
  }
}
```

Over REST, `POST /api/tools/execute` with `{"tool": "duckdb_query", "arguments": {...}}`; the response is `{"success": true, "result": {...}}`. Authenticate with `Authorization: Bearer <token>` or `X-API-Key: <key>`. See the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md) for protocol details.

---

## Limitations

- **Read-only.** `duckdb_query` rejects write/DDL keywords by substring match, so a column or literal containing e.g. `UPDATE` is also rejected.
- **Row caps.** `limit` maxes out at 10,000 (`duckdb_query`, `duckdb_aggregate`) or 1,000 (`duckdb_sql`); results are held in memory.
- **No per-file access control.** Every file in the data directory is queryable by anyone allowed to call the tools; restrict tool access with SAJHA roles/API-key scopes instead.
- **Trusted identifiers.** `table_name`, `group_by`, `having` and `order_by` are interpolated into SQL; they are meant for trusted callers.
- **File formats.** CSV needs consistent column counts and ideally a header row; JSON must be JSON or JSON Lines.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Table not found | Run `duckdb_list_tables`; check the view name derived from the file name; or query the file with `read_csv_auto('<path>')` |
| New file not visible | Wait for auto refresh or call `duckdb_refresh_views` with `reload_external_files: true` |
| "Forbidden operation" | The query contains a write/DDL keyword; rephrase (e.g. alias columns) |
| CSV parsed wrongly | Query with `read_csv('<path>', delim=',', header=true, columns={...})` |
| Dates read as strings | Convert with `STRPTIME(col, '%Y-%m-%d')` or `CAST(col AS DATE)` |
| Slow or memory-heavy query | Filter early, select only needed columns, prefer Parquet for large data, use `EXPLAIN` |

---

## Appendix: Useful DuckDB SQL

- **Aggregates:** `SUM`, `AVG`, `COUNT`, `MIN`, `MAX`, `STDDEV`, `STRING_AGG`, `PERCENTILE_CONT`
- **Strings:** `CONCAT`, `SUBSTRING`, `UPPER`, `LOWER`, `TRIM`, `REPLACE`, `SPLIT_PART`, `REGEXP_MATCHES`
- **Dates:** `CURRENT_DATE`, `DATE_TRUNC`, `DATE_PART`, `DATEDIFF`, `STRPTIME`, `STRFTIME`
- **Windows:** `ROW_NUMBER`, `RANK`, `DENSE_RANK`, `LAG`, `LEAD`, `NTILE`

| Use case | Format |
|----------|--------|
| Large or wide datasets | Parquet |
| Human-readable, small | CSV |
| Append-only event data | JSON Lines |

See the [Glossary](../../../GLOSSARY.md) for terms such as OLAP and columnar storage.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
