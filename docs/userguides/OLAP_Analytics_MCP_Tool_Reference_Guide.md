# OLAP Analytics MCP Tools - Reference Guide

**Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com**

## Version 2.9.0

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Getting Started](#getting-started)
4. [Semantic Layer](#semantic-layer)
5. [OLAP Tools Reference](#olap-tools-reference)
6. [Cohort Analysis](#cohort-analysis)
7. [Sample Data Generator](#sample-data-generator)
8. [Examples](#examples)
9. [Best Practices](#best-practices)
10. [Troubleshooting](#troubleshooting)

---

## Overview

The SAJHA OLAP Analytics module provides advanced multi-dimensional data analysis capabilities built on DuckDB. It offers a semantic layer that abstracts raw data into business-friendly concepts, enabling powerful analytics without requiring SQL expertise.

### Key Capabilities

| Capability | Description |
|------------|-------------|
| **Semantic Layer** | Business-friendly abstraction over raw data |
| **Pivot Tables** | Multi-dimensional aggregation with row/column pivoting |
| **ROLLUP & CUBE** | Hierarchical summaries with automatic subtotals |
| **Time Series** | Temporal analysis with period comparisons |
| **Window Functions** | Running totals, rankings, moving averages |
| **Statistics** | Comprehensive statistical analysis |
| **Contribution Analysis** | Pareto/ABC classification |

### Benefits

- **No SQL Required**: Define dimensions and measures once, use everywhere
- **Consistent Metrics**: Same measure definitions across all analyses
- **High Performance**: Leverages DuckDB's columnar storage and vectorized execution
- **Flexible**: From simple aggregations to complex cohort analysis
- **MCP Native**: All capabilities exposed as standard MCP tools

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    SAJHA OLAP Analytics                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   Semantic Layer                         │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │   │
│  │  │   Datasets   │  │   Measures   │  │  Dimensions  │   │   │
│  │  │   Registry   │  │  Definitions │  │  Hierarchies │   │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│  ┌───────────────────────────▼──────────────────────────────┐  │
│  │                    Query Engines                          │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐        │  │
│  │  │  Pivot  │ │ Rollup  │ │ Window  │ │  Time   │        │  │
│  │  │ Engine  │ │ Engine  │ │ Engine  │ │ Series  │        │  │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘        │  │
│  │  ┌─────────┐ ┌─────────┐                                 │  │
│  │  │  Stats  │ │ Top-N   │                                 │  │
│  │  │ Engine  │ │ Engine  │                                 │  │
│  │  └─────────┘ └─────────┘                                 │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              │                                  │
│  ┌───────────────────────────▼──────────────────────────────┐  │
│  │                    DuckDB Engine                          │  │
│  │          (Columnar Storage, Vectorized Execution)         │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Getting Started

### 1. Define Your Dataset

Create or modify `config/olap/datasets.json`:

```json
{
  "datasets": {
    "sales_analysis": {
      "name": "Sales Analysis",
      "description": "Sales data for multi-dimensional analysis",
      "source_table": "sales_data",
      "joins": [
        {
          "table": "customer_data",
          "type": "LEFT",
          "on": "sales_data.customer_id = customer_data.id"
        }
      ],
      "dimensions": ["date", "region", "product_category"],
      "measures": ["revenue", "quantity", "profit_margin"],
      "default_time_dimension": "date",
      "default_grain": "month"
    }
  }
}
```

### 2. Define Measures

Create or modify `config/olap/measures.json`:

```json
{
  "measures": {
    "revenue": {
      "name": "Revenue",
      "expression": "SUM(amount)",
      "format": "currency",
      "decimal_places": 2
    },
    "profit_margin": {
      "name": "Profit Margin %",
      "expression": "ROUND(100.0 * SUM(amount - cost) / NULLIF(SUM(amount), 0), 2)",
      "format": "percentage"
    }
  }
}
```

### 3. Define Dimensions

Create or modify `config/olap/dimensions.json`:

```json
{
  "dimensions": {
    "date": {
      "name": "Date",
      "type": "time",
      "column": "order_date",
      "hierarchies": {
        "calendar": {
          "levels": [
            {"name": "Year", "expression": "EXTRACT(YEAR FROM {column})"},
            {"name": "Quarter", "expression": "CONCAT('Q', EXTRACT(QUARTER FROM {column}))"},
            {"name": "Month", "expression": "STRFTIME({column}, '%Y-%m')"}
          ]
        }
      }
    }
  }
}
```

### 4. Use OLAP Tools

Now you can use any OLAP tool with your defined dataset:

```json
{
  "tool": "olap_pivot_table",
  "arguments": {
    "dataset": "sales_analysis",
    "rows": ["region"],
    "columns": ["product_category"],
    "values": [{"measure": "revenue", "aggregation": "SUM"}]
  }
}
```

---

## Semantic Layer

### Datasets

A dataset defines a logical view over one or more tables, including:

| Property | Description |
|----------|-------------|
| `name` | Display name |
| `source_table` | Primary table |
| `joins` | Related tables to include |
| `dimensions` | Available dimensions for grouping |
| `measures` | Available measures for aggregation |
| `default_time_dimension` | Primary time dimension |

### Measures

Measures define how values are aggregated:

| Property | Description |
|----------|-------------|
| `expression` | SQL aggregation expression |
| `format` | Output format (currency, percentage, number) |
| `decimal_places` | Precision for numeric output |

**Common Measure Expressions:**

```sql
-- Simple sum
"SUM(amount)"

-- Average
"ROUND(AVG(amount), 2)"

-- Count distinct
"COUNT(DISTINCT customer_id)"

-- Calculated ratio
"ROUND(100.0 * SUM(profit) / NULLIF(SUM(revenue), 0), 2)"

-- Conditional sum
"SUM(CASE WHEN status = 'completed' THEN amount ELSE 0 END)"
```

### Dimensions

Dimensions define how data is grouped:

| Property | Description |
|----------|-------------|
| `type` | `standard` or `time` |
| `column` | Source column |
| `hierarchies` | Drill-down levels |

---

## OLAP Tools Reference

### olap_list_datasets

List all available OLAP datasets.

**Parameters:**
- `include_schema` (boolean): Include detailed schema information

**Example:**
```json
{"include_schema": true}
```

---

### olap_describe_dataset

Get detailed information about a dataset.

**Parameters:**
- `dataset` (string, required): Dataset name

**Example:**
```json
{"dataset": "sales_analysis"}
```

---

### olap_pivot_table

Create a pivot table for multi-dimensional analysis.

**Parameters:**
- `dataset` (string, required): Dataset name
- `rows` (array, required): Row dimensions
- `columns` (array): Column dimensions to pivot
- `values` (array, required): Measures with aggregations
- `filters` (array): Filters to apply
- `include_totals` (boolean): Include grand totals
- `include_subtotals` (boolean): Include subtotals

**Example:**
```json
{
  "dataset": "sales_analysis",
  "rows": ["region", "product_category"],
  "columns": ["quarter"],
  "values": [
    {"measure": "revenue", "aggregation": "SUM"},
    {"measure": "profit_margin", "aggregation": "AVG"}
  ],
  "filters": [
    {"dimension": "date", "operator": ">=", "value": "2024-01-01"}
  ],
  "include_totals": true
}
```

**Sample Output:**
```
┌─────────────┬─────────────┬─────────┬─────────┬─────────┬─────────┬─────────┐
│ Region      │ Category    │   Q1    │   Q2    │   Q3    │   Q4    │  Total  │
├─────────────┼─────────────┼─────────┼─────────┼─────────┼─────────┼─────────┤
│ North       │ Electronics │ $1.2M   │ $1.4M   │ $1.5M   │ $1.8M   │ $5.9M   │
│ North       │ Furniture   │ $0.5M   │ $0.6M   │ $0.7M   │ $0.9M   │ $2.7M   │
│ South       │ Electronics │ $0.8M   │ $0.9M   │ $1.1M   │ $1.3M   │ $4.1M   │
│ South       │ Furniture   │ $0.3M   │ $0.4M   │ $0.5M   │ $0.6M   │ $1.8M   │
├─────────────┼─────────────┼─────────┼─────────┼─────────┼─────────┼─────────┤
│ Total       │             │ $2.8M   │ $3.3M   │ $3.8M   │ $4.6M   │ $14.5M  │
└─────────────┴─────────────┴─────────┴─────────┴─────────┴─────────┴─────────┘
```

---

### olap_hierarchical_summary

Create hierarchical summaries using ROLLUP or CUBE.

**Parameters:**
- `dataset` (string, required): Dataset name
- `dimensions` (array, required): Dimensions for grouping
- `measures` (array, required): Measures to aggregate
- `operation` (string): "ROLLUP" or "CUBE"
- `filters` (array): Filters to apply

**Example:**
```json
{
  "dataset": "sales_analysis",
  "dimensions": ["region", "product_category"],
  "measures": [{"measure": "revenue", "aggregation": "SUM"}],
  "operation": "ROLLUP"
}
```

**Output includes:**
- Detail rows for each combination
- Subtotals for each dimension level
- Grand total row

---

### olap_time_series

Analyze data over time with period comparisons.

**Parameters:**
- `dataset` (string, required): Dataset name
- `time_dimension` (string, required): Time dimension
- `time_grain` (string, required): year, quarter, month, week, day, hour
- `measures` (array, required): Measures to analyze
- `comparison` (object): Period comparison (yoy, mom, qoq, wow, dod)
- `fill_gaps` (boolean): Fill missing periods with zeros
- `date_range` (object): Start and end date filters

**Example - Monthly Revenue with YoY Comparison:**
```json
{
  "dataset": "sales_analysis",
  "time_dimension": "date",
  "time_grain": "month",
  "measures": ["revenue"],
  "comparison": {"type": "yoy"},
  "fill_gaps": true,
  "date_range": {
    "start": "2024-01-01",
    "end": "2024-12-31"
  }
}
```

**Output includes:**
- Current period values
- Previous period values
- Absolute change
- Percentage change

---

### olap_window_analysis

Apply window functions for advanced calculations.

**Parameters:**
- `dataset` (string, required): Dataset name
- `dimensions` (array, required): Dimensions to include
- `measures` (array): Base measures
- `calculations` (array, required): Window calculations

**Available Window Functions:**

| Function | Description |
|----------|-------------|
| `running_total` | Cumulative sum |
| `running_average` | Cumulative average |
| `moving_average` | Rolling average (specify window_size) |
| `rank` | Rank with gaps |
| `dense_rank` | Rank without gaps |
| `row_number` | Sequential numbering |
| `percent_rank` | Percentile rank (0-100) |
| `ntile` | Divide into N buckets |
| `lag` | Value from previous row |
| `lead` | Value from next row |
| `percent_of_total` | Percentage of partition total |
| `difference_from_previous` | Change from previous row |
| `percent_change` | % change from previous row |

**Example - Running Total and Rank:**
```json
{
  "dataset": "sales_analysis",
  "dimensions": ["region", "date"],
  "measures": ["revenue"],
  "calculations": [
    {
      "type": "running_total",
      "measure": "revenue",
      "partition_by": ["region"],
      "order_by": "date",
      "alias": "cumulative_revenue"
    },
    {
      "type": "rank",
      "measure": "revenue",
      "partition_by": ["date"],
      "direction": "DESC",
      "alias": "revenue_rank"
    }
  ]
}
```

---

### olap_statistics

Calculate comprehensive statistics.

**Parameters:**
- `dataset` (string, required): Dataset name
- `measures` (array, required): Measures to analyze
- `group_by` (array): Dimensions to group by
- `statistics` (array): Types: summary, percentiles, correlation, distribution
- `percentiles` (array): Custom percentile values

**Example:**
```json
{
  "dataset": "sales_analysis",
  "measures": ["revenue", "quantity"],
  "group_by": ["region"],
  "statistics": ["summary", "percentiles"],
  "percentiles": [0.25, 0.5, 0.75, 0.9, 0.99]
}
```

**Summary Statistics Output:**
- Count, Distinct Count
- Sum, Mean, Median
- Min, Max, Range
- Standard Deviation, Variance
- Coefficient of Variation

---

### olap_histogram

Generate histogram data for distribution analysis.

**Parameters:**
- `dataset` (string, required): Dataset name
- `measure` (string, required): Measure to analyze
- `bins` (integer): Number of bins (default: 10)
- `filters` (array): Filters to apply

**Example:**
```json
{
  "dataset": "sales_analysis",
  "measure": "revenue",
  "bins": 20
}
```

**Output includes:**
- Bin ranges
- Frequency counts
- Percentage of total
- Cumulative percentage

---

### olap_top_n

Get top or bottom N records.

**Parameters:**
- `dataset` (string, required): Dataset name
- `dimensions` (array, required): Dimensions to analyze
- `measure` (string, required): Measure for ranking
- `n` (integer): Number of records (default: 10)
- `direction` (string): "top" or "bottom"
- `include_others` (boolean): Aggregate remaining as "Others"

**Example:**
```json
{
  "dataset": "sales_analysis",
  "dimensions": ["product_category"],
  "measure": "revenue",
  "n": 5,
  "direction": "top",
  "include_others": true
}
```

---

### olap_contribution

Pareto analysis with A/B/C classification.

**Parameters:**
- `dataset` (string, required): Dataset name
- `dimension` (string, required): Dimension to analyze
- `measure` (string, required): Measure for contribution

**Example:**
```json
{
  "dataset": "sales_analysis",
  "dimension": "product_category",
  "measure": "revenue"
}
```

**Output includes:**
- Contribution percentage
- Cumulative percentage
- Pareto class (A=80%, B=95%, C=100%)

---

## Cohort Analysis

Cohort analysis is a powerful technique for understanding how groups of users behave over time. Version 2.9.0 introduces two specialized tools for cohort and retention analysis.

### olap_cohort_analysis

Track groups of users/customers over time to understand engagement, revenue, and retention patterns.

**Parameters:**
- `dataset` (string, required): Dataset name
- `cohort_dimension` (string, required): Dimension defining the cohort (e.g., 'signup_month')
- `time_dimension` (string, required): Time dimension for tracking
- `entity_dimension` (string, required): Entity to track (e.g., 'customer_id')
- `measure` (string, required): Measure to aggregate
- `aggregation` (string): COUNT_DISTINCT, SUM, or AVG (default: COUNT_DISTINCT)
- `time_grain` (string): year, quarter, month, week, day (default: month)
- `periods` (integer): Number of periods to track (default: 12)
- `show_percentages` (boolean): Show percentages vs absolute (default: true)

**Example - Customer Revenue Cohorts:**
```json
{
  "tool": "olap_cohort_analysis",
  "arguments": {
    "dataset": "sales_analysis",
    "cohort_dimension": "signup_month",
    "time_dimension": "order_month_start",
    "entity_dimension": "customer_id",
    "measure": "revenue",
    "aggregation": "SUM",
    "time_grain": "month",
    "periods": 12,
    "show_percentages": false
  }
}
```

**Sample Output (Cohort Matrix):**
```
┌─────────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ Cohort      │  Size    │ Period 0 │ Period 1 │ Period 2 │ Period 3 │ Period 4 │
├─────────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│ 2024-01     │   150    │ $45,000  │ $12,000  │ $8,500   │ $6,200   │ $4,800   │
│ 2024-02     │   175    │ $52,500  │ $14,700  │ $9,800   │ $7,100   │ --       │
│ 2024-03     │   200    │ $60,000  │ $16,800  │ $11,200  │ --       │ --       │
│ 2024-04     │   180    │ $54,000  │ $15,120  │ --       │ --       │ --       │
└─────────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

---

### olap_retention_analysis

Analyze what percentage of users from each cohort remain active in subsequent periods.

**Parameters:**
- `dataset` (string, required): Dataset name
- `cohort_dimension` (string, required): Dimension defining first activity
- `activity_dimension` (string, required): Dimension indicating ongoing activity
- `entity_dimension` (string, required): Entity to track
- `time_grain` (string): Time granularity (default: month)
- `periods` (integer): Number of periods (default: 12)

**Example - User Retention:**
```json
{
  "tool": "olap_retention_analysis",
  "arguments": {
    "dataset": "sales_analysis",
    "cohort_dimension": "customer_signup_date",
    "activity_dimension": "order_date",
    "entity_dimension": "customer_id",
    "time_grain": "month",
    "periods": 6
  }
}
```

**Sample Output (Retention Matrix):**
```
┌─────────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ Cohort      │  Size    │ Month 0  │ Month 1  │ Month 2  │ Month 3  │ Month 4  │ Month 5  │
├─────────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┼──────────┤
│ 2024-01     │   150    │  100%    │  68%     │  52%     │  45%     │  42%     │  40%     │
│ 2024-02     │   175    │  100%    │  72%     │  55%     │  48%     │  44%     │ --       │
│ 2024-03     │   200    │  100%    │  70%     │  54%     │  46%     │ --       │ --       │
│ 2024-04     │   180    │  100%    │  65%     │  50%     │ --       │ --       │ --       │
└─────────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

---

## Sample Data Generator

Version 2.9.0 includes a sample data generator for creating realistic demo datasets.

### olap_generate_sample_data

Generate sample sales data for demonstrations and testing.

**Parameters:**
- `num_customers` (integer): Number of customers (default: 500)
- `num_orders` (integer): Number of orders (default: 5000)
- `start_date` (string): Start date YYYY-MM-DD (default: 2023-01-01)
- `end_date` (string): End date YYYY-MM-DD (default: 2024-12-31)
- `save_config` (boolean): Save OLAP config files (default: true)

**Example:**
```json
{
  "tool": "olap_generate_sample_data",
  "arguments": {
    "num_customers": 1000,
    "num_orders": 10000,
    "start_date": "2022-01-01",
    "end_date": "2024-12-31",
    "save_config": true
  }
}
```

**Generated Data:**

The tool creates realistic sales data including:

| Table | Description |
|-------|-------------|
| `customers` | Customer profiles with segments, regions, signup dates |
| `products` | Products with categories, prices, costs |
| `orders` | Orders with quantities, amounts, discounts, profits |
| `sales_data` | Denormalized view for OLAP analysis |

**Generated Dimensions:**
- Region (North, South, East, West, Central)
- Product Category (Electronics, Furniture, Clothing, Food, Office Supplies)
- Customer Segment (Enterprise, Small Business, Consumer, Government)
- Time dimensions (Year, Quarter, Month, Week, Day)

**Generated Measures:**
- Revenue (SUM of net_amount)
- Quantity (SUM of quantity)
- Profit (SUM of profit)
- Profit Margin % (profit/revenue)
- Order Count (COUNT DISTINCT order_id)
- Customer Count (COUNT DISTINCT customer_id)
- Average Order Value

---

## Examples

### Example 1: Sales Dashboard Query

```json
{
  "tool": "olap_pivot_table",
  "arguments": {
    "dataset": "sales_analysis",
    "rows": ["region"],
    "columns": ["product_category"],
    "values": [
      {"measure": "revenue", "aggregation": "SUM"},
      {"measure": "quantity", "aggregation": "SUM"},
      {"measure": "profit_margin", "aggregation": "AVG"}
    ],
    "include_totals": true
  }
}
```

### Example 2: Year-over-Year Trend

```json
{
  "tool": "olap_time_series",
  "arguments": {
    "dataset": "sales_analysis",
    "time_dimension": "date",
    "time_grain": "month",
    "measures": ["revenue", "quantity"],
    "comparison": {"type": "yoy"}
  }
}
```

### Example 3: Customer Segmentation Analysis

```json
{
  "tool": "olap_hierarchical_summary",
  "arguments": {
    "dataset": "customer_analysis",
    "dimensions": ["segment", "region"],
    "measures": [
      {"measure": "customer_count", "aggregation": "SUM"},
      {"measure": "avg_spent", "aggregation": "AVG"}
    ],
    "operation": "CUBE"
  }
}
```

### Example 4: Running Totals with Rankings

```json
{
  "tool": "olap_window_analysis",
  "arguments": {
    "dataset": "sales_analysis",
    "dimensions": ["date", "region"],
    "measures": ["revenue"],
    "calculations": [
      {
        "type": "running_total",
        "measure": "revenue",
        "partition_by": ["region"],
        "order_by": "date",
        "alias": "ytd_revenue"
      },
      {
        "type": "percent_change",
        "measure": "revenue",
        "partition_by": ["region"],
        "order_by": "date",
        "alias": "revenue_growth_pct"
      }
    ]
  }
}
```

---

## Best Practices

### 1. Dataset Design

- **Keep datasets focused**: One dataset per analytical domain
- **Define clear joins**: Document relationship cardinality
- **Use meaningful names**: Business-friendly dimension/measure names

### 2. Measure Design

- **Use NULLIF**: Prevent division by zero
- **Round appropriately**: Use ROUND() for readability
- **Document formulas**: Add descriptions to measure definitions

### 3. Performance

- **Limit dimensions**: More dimensions = slower queries
- **Filter early**: Apply filters to reduce data volume
- **Use appropriate grains**: Don't over-aggregate

### 4. Analysis Patterns

- **Start broad, drill down**: Use ROLLUP for hierarchical analysis
- **Compare periods**: Use time series with YoY/MoM
- **Find outliers**: Use Top N and statistics together

---

## Troubleshooting

### Common Issues

**"Dataset not found"**
- Check dataset name in `config/olap/datasets.json`
- Ensure file is valid JSON
- Reload semantic layer

**"Measure not defined"**
- Add measure to `config/olap/measures.json`
- Check measure name spelling

**"Column not found"**
- Verify source table has the column
- Check dimension column mapping

**Empty Results**
- Check filters aren't too restrictive
- Verify source table has data
- Check date range parameters

### Debugging

Enable SQL output in tool responses to see generated queries:

```json
{
  "success": true,
  "data": [...],
  "sql": "SELECT ... FROM ..."
}
```

---

## API Reference

See full API documentation at `/api/docs` or use the MCP Studio interface for interactive exploration.

---

*Document Version: 2.9.0*
*Last Updated: February 2026*
