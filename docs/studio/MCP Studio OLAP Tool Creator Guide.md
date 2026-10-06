# MCP Studio OLAP Dataset Creator Guide

The OLAP page in MCP Studio defines **datasets** for the OLAP semantic layer. A dataset is a source table, optional joins, and the dimensions and measures that analysts may use. Unlike the other creators, it does not generate a tool. The OLAP tools that query these datasets already ship with SAJHA. They are documented in the [OLAP Analytics Tool Reference Guide](../tools/analytics/OLAP%20Analytics%20Tool%20Reference%20Guide.md).

Where Studio lives, the common create → preview → deploy workflow, where generated files are stored, hot reload and permissions are covered once in the [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md).

## Contents

1. [Opening the creator](#opening-the-creator)
2. [Concepts](#concepts)
3. [Form reference](#form-reference)
4. [What the page sends](#what-the-page-sends)
5. [How datasets are stored and loaded](#how-datasets-are-stored-and-loaded)
6. [Adding a dataset by hand](#adding-a-dataset-by-hand)
7. [Troubleshooting](#troubleshooting)

---

## Opening the creator

The page is served at `/studio/olap` and titled **OLAP Dataset Creator**. You can open it from the **OLAP Analytics** card on the Studio home page, from **MCP Studio → OLAP dataset** in the top menu, or from the **OLAP** chip in the Studio sub-navigation.

---

## Concepts

| Term | Meaning |
|------|---------|
| **Dataset** | A named, business-friendly view over a source table plus its joins |
| **Dimension** | A categorical attribute to group or filter by, such as region, product or date |
| **Measure** | A numeric aggregation, such as `SUM(amount)` or `COUNT(DISTINCT order_id)` |
| **Hierarchy** | A drill-down path inside a dimension, such as Year → Quarter → Month → Day |
| **Default time dimension** | The time dimension that time-series analysis uses when the caller does not name one |

---

## Form reference

### Dataset information

| Field | Required | Notes |
|-------|----------|-------|
| Dataset Name | Yes | Pattern `[a-z_]+`. Lowercase letters and underscores only, no digits. |
| Display Name | No | |
| Description | No | |
| Source Table | Yes | A table or view name, or a DuckDB table function such as `read_csv_auto('${data.duckdb.dir}/sales.csv')`. |

### Table Joins (optional)

Click **Add Join** for each join. Each join row has:

| Field | Values |
|-------|--------|
| Table name | A table, view or DuckDB table function |
| Join type | `LEFT` (default), `INNER`, `RIGHT` or `FULL` |
| ON clause | For example `sales_data.customer_id = customer_data.id` |
| Alias | Optional |

A join row is dropped unless it has both a table and an ON clause.

### Dimensions

Click **Add Dimension**. Each row has **Name**, **Column**, and **Type** (`Standard` or `Time/Date`). Dimensions of type `Time/Date` appear in the **Default Time Dimension** list.

### Measures

Click **Add Measure**. Each row has **Name**, **Expression** (for example `SUM(amount)`), **Format** (`Number`, `Currency` or `Percentage`) and **Description**.

### Time Configuration

**Default Time Dimension** offers `None` plus every dimension of type `Time/Date`.

### Buttons

- **Validate**: runs in the browser and checks that the dataset name, the source table, at least one dimension and at least one measure are present.
- **Reset**: clears the form.
- **Deploy Dataset**: validates, then posts the configuration to `/admin/studio/olap/deploy`.

> Deploy adds the dataset to `config/olap/datasets.json`, adds the page's new dimension and measure definitions to `dimensions.json` and `measures.json`, and re-creates the OLAP tools, so the dataset can be queried at once. It refuses a dataset name that already exists. `POST /admin/studio/olap/delete` with `{"name": ...}` removes a dataset Studio created, and the definitions it added. See [Action endpoints](MCP%20Studio%20User%20Guide.md#action-endpoints-deploy-load-and-delete).

---

## What the page sends

The **Configuration Preview** panel shows the exact body that **Deploy Dataset** posts:

```json
{
  "name": "sales_analysis",
  "display_name": "Sales Analysis",
  "description": "Sales with customer and product attributes",
  "source_table": "sales_data",
  "joins": [
    { "table": "customer_data", "type": "LEFT",
      "on": "sales_data.customer_id = customer_data.id", "alias": "customers" }
  ],
  "dimensions": ["order_date", "region", "customer_segment"],
  "measures": ["revenue", "order_count"],
  "default_time_dimension": "order_date",
  "dimension_definitions": [
    { "name": "order_date", "column": "order_date", "type": "time" },
    { "name": "region", "column": "region", "type": "standard" }
  ],
  "measure_definitions": [
    { "name": "revenue", "expression": "SUM(amount)", "format": "currency", "description": "" }
  ]
}
```

The dataset itself lists dimensions and measures by **name**. The Column and Type of each dimension, and the Expression, Format and Description of each measure (rows without an expression are skipped), travel in `dimension_definitions` and `measure_definitions`. On deploy, a definition whose name is not yet in `dimensions.json` or `measures.json` is added there; an existing definition of the same name is kept unchanged.

---

## How datasets are stored and loaded

There is no OLAP generator class in `sajha/studio/`; Studio's deploy endpoint edits these files directly. The semantic layer (`sajha/olap/semantic_layer.py`) reads three files from `config/olap/`:

| File | Top-level key | Contents |
|------|---------------|----------|
| `datasets.json` | `datasets` | A map of dataset name to `display_name`, `description`, `source_table`, `joins`, `dimensions`, `measures`, `default_time_dimension` and optionally `row_level_security` |
| `dimensions.json` | `dimensions` | A map of dimension name to `name`, `column`, `type` (`standard` or `time`), `description`, and optional `hierarchies`, where each hierarchy has `levels` of `{name, expression, column}` |
| `measures.json` | `measures` | A map of measure name to `name`, `expression`, `format`, `description` and optional `requires_window` |

Name resolution works like this:

- A dimension name found in `dimensions.json` resolves to its `column`, or to a hierarchy level's `expression` when the caller asks for a hierarchy level. An unknown name is used as a raw column reference.
- A measure name found in `measures.json` resolves to its `expression`. An unknown name becomes `SUM(<name>)`.

The OLAP tool classes in `sajha/tools/impl/duckdb_olap_advanced.py` build a `SemanticLayer` when the tool is created. The directory comes from the tool config's `config_path`, or `config/olap` by default. The Studio hot-reload watcher covers `config/tools/` and `sajha/tools/impl/`, but not `config/olap/`. After editing these files, use **Reload All** on **Admin → Tools** (`POST /api/admin/tools/reload`) or restart the server.

`${...}` placeholders in a source table or join, such as `${data.duckdb.dir}`, use the same `config/application.yml` variables as tool configs. The shipped `datasets.json` uses them for CSV-backed datasets.

---

## Adding a dataset by hand

1. Build the dataset on the page, click **Validate**, and copy the **Configuration Preview** JSON.
2. Add it to `config/olap/datasets.json` under `datasets`, keyed by its name. Drop the inner `name` field, because the key is the name.
3. For every dimension name that is not already defined, add an entry to `config/olap/dimensions.json`:

   ```json
   "region": { "name": "Region", "column": "region", "type": "standard",
               "description": "Sales region" }
   ```

   A time dimension with a calendar hierarchy:

   ```json
   "order_date": {
     "name": "Order Date", "column": "order_date", "type": "time",
     "hierarchies": { "calendar": { "levels": [
       { "name": "Year",    "expression": "EXTRACT(YEAR FROM order_date)" },
       { "name": "Quarter", "expression": "CONCAT('Q', EXTRACT(QUARTER FROM order_date))" },
       { "name": "Month",   "expression": "STRFTIME(order_date, '%Y-%m')" }
     ] } }
   }
   ```

4. For every new measure name, add an entry to `config/olap/measures.json`:

   ```json
   "revenue": { "name": "Revenue", "expression": "SUM(amount)",
                "format": "currency", "description": "Total sales revenue" }
   ```

5. Use **Reload All** on **Admin → Tools**, then call an OLAP tool such as `olap_pivot_table` with the new dataset name.

Use the shipped entries in `config/olap/*.json`, such as `sales_analysis`, as working references.

---

## Troubleshooting

| Symptom | Likely cause | What to check |
|---------|--------------|---------------|
| **Deploy Dataset** reports a deployment error | The name is taken, or a required field is missing | The status message says which. Pick another name, or delete the Studio-created dataset first. |
| Dataset name rejected by the browser | Pattern `[a-z_]+` | No digits, capitals or hyphens. |
| New dataset not visible to the OLAP tools | Semantic layer not reloaded | Use **Reload All** on **Admin → Tools**, or restart the server. |
| A measure aggregates the wrong thing | No definition in `measures.json`, so it fell back to `SUM(<name>)` | Add the measure definition. |
| Errors loading datasets in the log | Invalid JSON, or a dataset without `source_table` | Validate the file, since `source_table` is required. |

---

## Related documentation

- [MCP Studio User Guide](MCP%20Studio%20User%20Guide.md)
- [OLAP Analytics Tool Reference Guide](../tools/analytics/OLAP%20Analytics%20Tool%20Reference%20Guide.md)
- [DuckDB Tool Reference Guide](../tools/analytics/DuckDB%20Tool%20Reference%20Guide.md)
- [Storage Guide](../getting-started/Storage%20Guide.md)
- [Glossary](../../GLOSSARY.md)

---

Copyright © 2025–2030, Ashutosh Sinha. All rights reserved.
