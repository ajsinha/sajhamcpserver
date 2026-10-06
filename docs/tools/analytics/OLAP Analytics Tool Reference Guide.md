# OLAP Analytics Tool Reference Guide

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Semantic Layer](#semantic-layer)
4. [Tools](#tools)
5. [Calling the Tools](#calling-the-tools)
6. [Best Practices](#best-practices)
7. [Troubleshooting](#troubleshooting)

---

## Overview

The OLAP Analytics tools provide multi-dimensional analysis (pivot tables, time series with period comparisons) over CSV data using DuckDB. A semantic layer in `config/olap/` maps raw tables to business-friendly datasets, dimensions and measures, so callers name dimensions and measures instead of writing SQL.

| Tool | Implementation | Purpose |
|------|----------------|---------|
| `customer_olap_pivot` | `duckdb_olap_advanced.CustomerOLAPTool` | Pivot customer/order/product data by fixed customer dimensions and measures |
| `olap_pivot_table` | `duckdb_olap_advanced.DuckDBOLAPAdvancedTool` | Pivot any semantic-layer dataset (rows, columns, values, totals) |
| `olap_time_series` | `duckdb_olap_advanced.DuckDBOLAPAdvancedTool` | Time-grain aggregation with gap filling and YoY/QoQ/MoM comparisons |

For ad-hoc SQL over the same CSV files, see `duckdb_sql` and the `duckdb_*` tools in the [DuckDB Tool Reference Guide](DuckDB%20Tool%20Reference%20Guide.md).

---

## Architecture

```
 MCP / REST call
       │
       ▼
 ┌──────────────────────────────┐      ┌──────────────────────────┐
 │ OLAP tools                   │◄─────│ Semantic layer           │
 │  customer_olap_pivot         │      │  config/olap/datasets    │
 │  olap_pivot_table            │      │  config/olap/dimensions  │
 │  olap_time_series            │      │  config/olap/measures    │
 └──────────────┬───────────────┘      └──────────────────────────┘
                │ generated SQL
                ▼
 ┌──────────────────────────────────────────┐
 │ DuckDB                                   │
 │  customer_olap: read_csv_auto(<data dir>/│
 │    customers|orders|products.csv)        │
 │  other datasets: sample star schema      │
 │    (see "Sample data" below)             │
 └──────────────────────────────────────────┘
```

`customer_olap_pivot` and the `customer_olap` dataset read CSV files from the data directory, `data.duckdb.dir` in `config/application.yml` (default `./data/duckdb`); each tool's config passes it as `data_directory`, and the files are `customers.csv`, `orders.csv` and `products.csv`. The other datasets read tables from DuckDB (see [Sample data](#sample-data)). See the [Configuration Reference](../../getting-started/Configuration%20Reference.md) and the [Storage Guide](../../getting-started/Storage%20Guide.md).

---

## Semantic Layer

The semantic layer lives in three files under `config/olap/`.

### Datasets (`datasets.json`)

A dataset is a logical view over one or more tables:

| Property | Description |
|----------|-------------|
| `name`, `display_name`, `description` | Identification |
| `source_table` | Primary table, e.g. `read_csv_auto('${data.duckdb.dir}/customers.csv')` |
| `joins` | Related tables (`table`, `type`, `on`, `alias`) |
| `dimensions` | Dimensions available for grouping |
| `measures` | Measures available for aggregation |
| `default_time_dimension` | Primary time dimension |

Shipped datasets and the relation each reads:

| Dataset | `source_table` | Grain |
|---------|----------------|-------|
| `customer_olap` | `customers.csv` joined to `orders.csv` and `products.csv` | order line |
| `sales_analysis` | `sales_data` view | order |
| `financial_metrics` | `sales_data` view | order |
| `customer_analytics` | `customer_data` view | customer and order (customers without orders appear once) |
| `inventory_analysis` | `inventory_data` table | product and warehouse (stock snapshot) |

A join's `on` clause must use the join's `alias` when one is set (the generated SQL is `<type> JOIN <table> AS <alias> ON <on>`), and the joined relations must not share column names that dimensions or measures reference, because dimension and measure columns are unqualified. A dataset with joins looks like this (`customer_olap` in `datasets.json` is the shipped example):

```json
{
  "datasets": {
    "orders_by_customer": {
      "name": "orders_by_customer",
      "display_name": "Orders by Customer",
      "source_table": "orders",
      "joins": [
        {"table": "customers", "type": "LEFT",
         "on": "orders.customer_id = c.customer_id", "alias": "c"}
      ],
      "dimensions": ["order_date"],
      "measures": ["order_count"],
      "default_time_dimension": "order_date"
    }
  }
}
```

### Measures (`measures.json`)

| Property | Description |
|----------|-------------|
| `expression` | SQL aggregation expression |
| `format` | Output format (`currency`, `percentage`, `number`) |
| `decimal_places` | Numeric precision |

Typical expressions: `SUM(amount)`, `COUNT(DISTINCT customer_id)`, `ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2)`, `SUM(CASE WHEN status = 'completed' THEN amount ELSE 0 END)`.

### Dimensions (`dimensions.json`)

| Property | Description |
|----------|-------------|
| `type` | `standard` or `time` |
| `column` | Source column |
| `hierarchies` | Optional drill-down levels (e.g. Year → Quarter → Month) |

---

## Tools

### customer_olap_pivot

Pivot table over the joined customers/orders/products CSVs, with a fixed set of dimensions and measures.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `rows` | array of string | Yes | | Row dimensions: `customer_segment`, `customer_tier`, `region`, `country`, `acquisition_channel`, `age_group`, `product_category`, `product_name`, `payment_method`, `sales_rep` |
| `columns` | array of string | No | | Column (pivot) dimensions, typically `order_date` |
| `measures` | array of string | Yes | | `order_count`, `customer_count`, `total_revenue`, `total_quantity`, `avg_order_value`, `total_discount`, `total_shipping`, `avg_discount_pct`, `gross_profit`, `profit_margin` |
| `filters` | object | No | | Key/value filters; a list value means IN, e.g. `{"customer_tier": ["Gold", "Platinum"]}` |
| `order_by` | string | No | | Sort column; prefix with `-` for descending |
| `limit` | integer | No | 100 | 1–1000 |

Response fields: `success`, `columns`, `data`, `row_count`, `query`, `execution_time_ms`.

```json
{
  "rows": ["customer_segment", "region"],
  "measures": ["total_revenue", "order_count"],
  "filters": {"customer_tier": ["Gold", "Platinum"]},
  "order_by": "-total_revenue",
  "limit": 20
}
```

### olap_pivot_table

Pivot table over a semantic-layer dataset.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `dataset` | string | Yes | | Dataset name from `config/olap/datasets.json` |
| `rows` | array of string | Yes | | Row dimensions |
| `columns` | array of string | No | | Dimensions to pivot into columns |
| `values` | array of object | Yes | | `{"measure": "...", "aggregation": "SUM"}` items |
| `filters` | array of object | No | | `{"dimension": "...", "operator": ">=", "value": ...}` items |
| `include_totals` | boolean | No | true | Grand totals row |
| `include_subtotals` | boolean | No | false | Subtotals per dimension level |

```json
{
  "dataset": "sales_analysis",
  "rows": ["region", "product_category"],
  "columns": ["quarter"],
  "values": [
    {"measure": "revenue", "aggregation": "SUM"},
    {"measure": "profit_margin", "aggregation": "AVG"}
  ],
  "filters": [{"dimension": "order_date", "operator": ">=", "value": "2024-01-01"}],
  "include_totals": true
}
```

### olap_time_series

Aggregate measures over a time dimension with optional period comparison.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `dataset` | string | Yes | | Dataset name |
| `time_dimension` | string | Yes | | Time dimension, e.g. `order_date`, `signup_date` |
| `time_grain` | string | Yes | | `year`, `quarter`, `month`, `week`, `day`, `hour` |
| `measures` | array of string | Yes | | Measures to analyze |
| `comparison` | object | No | | `{"type": "yoy" \| "qoq" \| "mom" \| "wow" \| "dod"}` |
| `fill_gaps` | boolean | No | true | Fill missing periods with zeros |
| `date_range` | object | No | | `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}` |

Output includes current and previous period values, absolute change and percentage change when `comparison` is set.

```json
{
  "dataset": "sales_analysis",
  "time_dimension": "order_date",
  "time_grain": "month",
  "measures": ["revenue"],
  "comparison": {"type": "yoy"},
  "date_range": {"start": "2024-01-01", "end": "2024-12-31"}
}
```

> **How these tools run.** `olap_pivot_table` and `olap_time_series` are served by the multi-operation `DuckDBOLAPAdvancedTool`; the registered tool name selects the operation and `tools/list` advertises that operation's schema. The semantic layer is read from `config/olap/`.

### Sample data

`DuckDBOLAPAdvancedTool` opens the DuckDB file `olap.duckdb` in a `data` folder next to the OLAP config folder when that file exists (with the default `config/olap`, the file `olap.duckdb` under `config`'s `data` folder), and an in-memory DuckDB otherwise. When the database has no `sales_data`, it loads a deterministic sample star schema (`sajha/olap/sample_data_generator.py`, fixed seed, 200 customers and 2,000 orders in 2023–2024), so every shipped semantic-layer dataset answers queries out of the box. When `sales_data` already exists, only a missing `customer_data` or `inventory_data` is added, and only if the tables it is built from are present; existing tables are never replaced. Set `"generate_sample_data": false` in the tool config to skip all of this.

| Relation | Kind | Columns | Used by |
|----------|------|---------|---------|
| `customers` | table | `customer_id`, `customer_name`, `segment`, `region`, `signup_date`, `lifetime_value`, `is_active`, `city`, `state`, `tier` (Bronze, Silver, Gold, Platinum by lifetime value) | the views below |
| `products` | table | `product_id`, `product_name`, `category`, `unit_price`, `unit_cost`, `margin_pct` | the views below, `inventory_data` |
| `orders` | table | `order_id`, `order_date`, `customer_id`, `product_id`, `quantity`, `unit_price`, `amount`, `discount`, `net_amount`, `cost`, `profit`, `region`, `segment`, `category`, `payment_method`, `is_returned` | the views below |
| `sales_data` | view | orders joined to customers and products, plus the aliases the semantic layer uses (`date`, `quarter`, `qty`, `sales_rep`, ...) | `sales_analysis`, `financial_metrics` |
| `customer_data` | view | customer columns (`customer_id`, `id`, `customer_name`, `segment`, `tier`, `region`, `state`, `city`, `signup_date`, `signup_month`, `lifetime_value`, `is_active`) and order columns (`order_id`, `order_date`, `product_id`, `product_name`, `category`, `quantity`, `amount`, `discount`, `net_amount`, `profit`; NULL for customers without orders) | `customer_analytics` |
| `inventory_data` | table | `product_id`, `product_name`, `category`, `warehouse` (Northeast, Southeast, Central and West DC), `warehouse_location`, `supplier` (two per category), `unit_cost`, `unit_price`, `avg_daily_demand`, `lead_time_days`, `reorder_point`, `stock_qty`, `snapshot_date` (2024-12-31), `inventory_value`, `days_of_supply`, `stock_status` (Healthy, Reorder, Overstock, Out of Stock) | `inventory_analysis` |

`olap_generate_sample_data` (an operation of `DuckDBOLAPAdvancedTool`) regenerates all of these with other sizes and dates.

```json
{"dataset": "customer_analytics", "rows": ["customer_segment"], "columns": ["customer_tier"],
 "values": [{"measure": "customer_count"}, {"measure": "avg_customer_value"}]}
```

```json
{"dataset": "inventory_analysis", "rows": ["warehouse"], "columns": ["product_category"],
 "values": [{"measure": "total_value"}, {"measure": "days_of_supply"}]}
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
    "name": "customer_olap_pivot",
    "arguments": {"rows": ["region"], "measures": ["total_revenue"]}
  }
}
```

Over REST, `POST /api/tools/execute` with `{"tool": "customer_olap_pivot", "arguments": {...}}`; the response is `{"success": true, "result": {...}}`. Authenticate with `Authorization: Bearer <token>` or `X-API-Key: <key>`. See the [MCP Protocol Guide](../../protocol/MCP%20Protocol%20Guide.md) for sessions, protocol versions and transports.

---

## Best Practices

- **Datasets**: keep one dataset per analytical domain; use business-friendly dimension and measure names.
- **Measures**: guard ratios with `NULLIF` and round with `ROUND()`.
- **Performance**: fewer dimensions and early filters keep queries fast; pick the coarsest useful time grain.
- **Analysis**: start broad and drill down; use time series with YoY/MoM to compare periods.

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Dataset not found | Name in `config/olap/datasets.json`; file is valid JSON |
| Measure/dimension not defined | Entry in `measures.json` / `dimensions.json` and listed on the dataset |
| File or column not found | `customer_olap`: CSVs exist in `data.duckdb.dir`. Other datasets: the relation in [Sample data](#sample-data) exists (a configured `olap.duckdb` must provide it); dimension `column` mapping matches the column name |
| Empty results | Filters or `date_range` too restrictive |
| Unexpected SQL | `customer_olap_pivot` returns the generated SQL in `query` |

See the [Glossary](../../../GLOSSARY.md) for OLAP terms.

---

*Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.*
