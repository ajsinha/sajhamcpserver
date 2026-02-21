# MCP Studio OLAP Tool Creator Guide
## SAJHA MCP Server v2.9.8

## Overview

The OLAP (Online Analytical Processing) Tool Creator enables you to build powerful analytical tools for multi-dimensional data analysis, pivot tables, time series analysis, cohort analytics, and statistical computations. Create business intelligence tools that transform raw data into actionable insights.

## Table of Contents

1. [Getting Started](#getting-started)
2. [OLAP Concepts](#olap-concepts)
3. [Creating OLAP Tools](#creating-olap-tools)
4. [Pivot Table Analysis](#pivot-table-analysis)
5. [Time Series Analysis](#time-series-analysis)
6. [Cohort Analysis](#cohort-analysis)
7. [Statistical Analysis](#statistical-analysis)
8. [Window Functions](#window-functions)
9. [Customer Analytics Example](#customer-analytics-example)
10. [Best Practices](#best-practices)
11. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Accessing the OLAP Tool Creator

1. Navigate to `http://localhost:3002/admin/studio`
2. Click on **OLAP Analytics Tool** card
3. Or access OLAP tools at: `http://localhost:3002/admin/studio/olap`

### Prerequisites

- Admin role access
- DuckDB or compatible analytics database
- Data files (CSV, Parquet, JSON) or database tables
- Understanding of dimensional modeling

---

## OLAP Concepts

### Dimensions vs Measures

| Concept | Description | Examples |
|---------|-------------|----------|
| **Dimensions** | Categorical attributes for grouping | Region, Product, Date, Customer Segment |
| **Measures** | Numeric values for aggregation | Revenue, Quantity, Profit, Count |

### OLAP Operations

| Operation | Description |
|-----------|-------------|
| **Slice** | Select a single dimension value |
| **Dice** | Select multiple dimension values |
| **Roll-up** | Aggregate to higher level (City → Region → Country) |
| **Drill-down** | Disaggregate to lower level (Year → Quarter → Month) |
| **Pivot** | Rotate dimensions between rows and columns |

---

## Creating OLAP Tools

### Step 1: Define Dataset

```json
{
  "dataset": {
    "name": "sales_analysis",
    "display_name": "Sales Analysis Dataset",
    "description": "Multi-dimensional sales data for analytics",
    "source": {
      "type": "csv",
      "path": "${data.dir}/sales_data.csv"
    }
  }
}
```

### Step 2: Define Dimensions

```json
{
  "dimensions": {
    "region": {
      "column": "region",
      "type": "string",
      "hierarchy": ["country", "region", "city"]
    },
    "product_category": {
      "column": "category",
      "type": "string"
    },
    "order_date": {
      "column": "order_date",
      "type": "date",
      "time_grains": ["year", "quarter", "month", "week", "day"]
    },
    "customer_segment": {
      "column": "segment",
      "type": "string",
      "values": ["Consumer", "Corporate", "Enterprise", "Government"]
    }
  }
}
```

### Step 3: Define Measures

```json
{
  "measures": {
    "total_revenue": {
      "expression": "SUM(amount)",
      "format": "currency"
    },
    "order_count": {
      "expression": "COUNT(*)",
      "format": "integer"
    },
    "avg_order_value": {
      "expression": "AVG(amount)",
      "format": "currency"
    },
    "profit_margin": {
      "expression": "SUM(profit) / NULLIF(SUM(revenue), 0) * 100",
      "format": "percentage"
    }
  }
}
```

### Step 4: Deploy Tool

Click **Deploy Tool** to create the OLAP analytics tool.

---

## Pivot Table Analysis

### Basic Pivot Configuration

```json
{
  "name": "sales_pivot",
  "tool_type": "olap_pivot",
  "dataset": "sales_analysis",
  "inputSchema": {
    "type": "object",
    "properties": {
      "rows": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Dimensions for row headers"
      },
      "columns": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Dimensions for column headers"
      },
      "measures": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Measures to aggregate"
      },
      "filters": {
        "type": "object",
        "description": "Filter conditions"
      }
    }
  }
}
```

### Example Usage

**Input:**
```json
{
  "rows": ["region", "product_category"],
  "columns": ["quarter"],
  "measures": ["total_revenue", "order_count"],
  "filters": {
    "year": 2024,
    "customer_segment": ["Enterprise", "Corporate"]
  }
}
```

**Output:**
```
┌──────────┬─────────────┬─────────────────┬─────────────────┬─────────────────┬─────────────────┐
│ Region   │ Category    │ Q1 Revenue      │ Q1 Orders       │ Q2 Revenue      │ Q2 Orders       │
├──────────┼─────────────┼─────────────────┼─────────────────┼─────────────────┼─────────────────┤
│ North    │ Electronics │ $125,450.00     │ 234             │ $142,890.00     │ 267             │
│ North    │ Furniture   │ $89,230.00      │ 156             │ $95,670.00      │ 178             │
│ South    │ Electronics │ $98,760.00      │ 189             │ $112,340.00     │ 215             │
│ South    │ Furniture   │ $67,890.00      │ 123             │ $73,450.00      │ 134             │
└──────────┴─────────────┴─────────────────┴─────────────────┴─────────────────┴─────────────────┘
```

### Pivot Options

```json
{
  "pivot_options": {
    "include_totals": true,
    "include_subtotals": true,
    "sort_by": "total_revenue",
    "sort_direction": "DESC",
    "limit": 100,
    "null_handling": "show_as_zero"
  }
}
```

---

## Time Series Analysis

### Time Series Configuration

```json
{
  "name": "revenue_trend",
  "tool_type": "olap_timeseries",
  "dataset": "sales_analysis",
  "inputSchema": {
    "type": "object",
    "properties": {
      "time_dimension": {
        "type": "string",
        "description": "Date/time column"
      },
      "time_grain": {
        "type": "string",
        "enum": ["year", "quarter", "month", "week", "day", "hour"]
      },
      "measures": {
        "type": "array",
        "items": {"type": "string"}
      },
      "comparison": {
        "type": "string",
        "enum": ["yoy", "qoq", "mom", "wow", "dod"]
      }
    }
  }
}
```

### Example: Year-over-Year Comparison

**Input:**
```json
{
  "time_dimension": "order_date",
  "time_grain": "month",
  "measures": ["total_revenue"],
  "comparison": "yoy",
  "date_range": {
    "start": "2024-01-01",
    "end": "2024-12-31"
  }
}
```

**Output:**
```json
{
  "data": [
    {
      "period": "2024-01",
      "total_revenue": 125000,
      "prior_period_revenue": 98000,
      "yoy_change": 27551,
      "yoy_change_pct": 28.1
    },
    {
      "period": "2024-02",
      "total_revenue": 142000,
      "prior_period_revenue": 112000,
      "yoy_change": 30000,
      "yoy_change_pct": 26.8
    }
  ]
}
```

### Moving Averages and Trends

```json
{
  "time_series_options": {
    "fill_gaps": true,
    "moving_average": {
      "enabled": true,
      "window": 7,
      "type": "simple"
    },
    "trend_line": {
      "enabled": true,
      "type": "linear"
    },
    "seasonality_detection": true
  }
}
```

---

## Cohort Analysis

### Cohort Configuration

```json
{
  "name": "customer_retention",
  "tool_type": "olap_cohort",
  "dataset": "customer_orders",
  "inputSchema": {
    "type": "object",
    "properties": {
      "cohort_date_column": {
        "type": "string",
        "description": "Column for cohort assignment (e.g., signup_date)"
      },
      "activity_date_column": {
        "type": "string",
        "description": "Column for activity tracking (e.g., order_date)"
      },
      "cohort_grain": {
        "type": "string",
        "enum": ["month", "week", "quarter"]
      },
      "metric": {
        "type": "string",
        "enum": ["retention", "revenue", "orders"]
      }
    }
  }
}
```

### Example: Customer Retention Cohort

**Input:**
```json
{
  "cohort_date_column": "signup_date",
  "activity_date_column": "order_date",
  "cohort_grain": "month",
  "metric": "retention",
  "periods": 6
}
```

**Output:**
```
Cohort Retention Analysis
┌─────────────┬─────────┬─────────┬─────────┬─────────┬─────────┬─────────┐
│ Cohort      │ Month 0 │ Month 1 │ Month 2 │ Month 3 │ Month 4 │ Month 5 │
├─────────────┼─────────┼─────────┼─────────┼─────────┼─────────┼─────────┤
│ Jan 2024    │ 100%    │ 45%     │ 32%     │ 28%     │ 25%     │ 23%     │
│ Feb 2024    │ 100%    │ 48%     │ 35%     │ 30%     │ 27%     │ -       │
│ Mar 2024    │ 100%    │ 52%     │ 38%     │ 33%     │ -       │ -       │
│ Apr 2024    │ 100%    │ 50%     │ 36%     │ -       │ -       │ -       │
└─────────────┴─────────┴─────────┴─────────┴─────────┴─────────┴─────────┘
```

---

## Statistical Analysis

### Descriptive Statistics

```json
{
  "name": "sales_statistics",
  "tool_type": "olap_stats",
  "inputSchema": {
    "type": "object",
    "properties": {
      "measure": {"type": "string"},
      "group_by": {"type": "array", "items": {"type": "string"}},
      "statistics": {
        "type": "array",
        "items": {
          "type": "string",
          "enum": ["mean", "median", "std", "variance", "min", "max", "percentile_25", "percentile_75", "percentile_90", "percentile_95", "percentile_99"]
        }
      }
    }
  }
}
```

### Distribution Analysis

```json
{
  "statistics_options": {
    "histogram": {
      "enabled": true,
      "bins": 20
    },
    "distribution_fit": {
      "enabled": true,
      "test_distributions": ["normal", "lognormal", "exponential"]
    },
    "outlier_detection": {
      "enabled": true,
      "method": "iqr",
      "threshold": 1.5
    }
  }
}
```

---

## Window Functions

### Ranking Analysis

```json
{
  "name": "sales_ranking",
  "tool_type": "olap_window",
  "inputSchema": {
    "type": "object",
    "properties": {
      "partition_by": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Columns to partition by"
      },
      "order_by": {
        "type": "string",
        "description": "Column to order by"
      },
      "window_functions": {
        "type": "array",
        "items": {
          "type": "string",
          "enum": ["rank", "dense_rank", "row_number", "ntile", "lead", "lag", "first_value", "last_value", "running_total", "running_avg", "percent_rank"]
        }
      }
    }
  }
}
```

### Example: Running Totals

**Input:**
```json
{
  "partition_by": ["region"],
  "order_by": "order_date",
  "measure": "revenue",
  "window_functions": ["running_total", "running_avg", "rank"]
}
```

**Output:**
```json
{
  "data": [
    {
      "region": "North",
      "order_date": "2024-01-01",
      "revenue": 5000,
      "running_total": 5000,
      "running_avg": 5000,
      "rank": 1
    },
    {
      "region": "North",
      "order_date": "2024-01-02",
      "revenue": 7500,
      "running_total": 12500,
      "running_avg": 6250,
      "rank": 2
    }
  ]
}
```

---

## Customer Analytics Example

### Complete Customer OLAP Tool

```json
{
  "name": "customer_olap_pivot",
  "description": "Multi-dimensional customer analytics with pivot table support",
  "implementation": "sajha.tools.impl.duckdb_olap_advanced.CustomerOLAPTool",
  "version": "2.9.8",
  "data_directory": "${data.duckdb.dir}",
  "dimensions": {
    "customer_segment": {
      "column": "customers.customer_segment",
      "values": ["Consumer", "Enterprise", "Small Business", "Government"]
    },
    "customer_tier": {
      "column": "customers.customer_tier",
      "values": ["Bronze", "Silver", "Gold", "Platinum"]
    },
    "region": {
      "column": "customers.region",
      "values": ["North", "South", "East", "West", "Central"]
    },
    "product_category": {
      "column": "orders.product_category"
    },
    "acquisition_channel": {
      "column": "customers.acquisition_channel"
    }
  },
  "measures": {
    "total_revenue": "ROUND(SUM(orders.quantity * orders.unit_price), 2)",
    "order_count": "COUNT(DISTINCT orders.order_id)",
    "customer_count": "COUNT(DISTINCT customers.customer_id)",
    "avg_order_value": "ROUND(AVG(orders.quantity * orders.unit_price), 2)",
    "gross_profit": "ROUND(SUM((orders.unit_price - products.unit_cost) * orders.quantity), 2)"
  }
}
```

### Usage Examples

**Revenue by Segment and Region:**
```json
{
  "rows": ["customer_segment", "region"],
  "measures": ["total_revenue", "order_count", "customer_count"]
}
```

**Product Performance by Tier:**
```json
{
  "rows": ["product_category"],
  "columns": ["customer_tier"],
  "measures": ["total_revenue", "gross_profit"],
  "filters": {"region": ["North", "East"]}
}
```

**Sales Rep Analysis:**
```json
{
  "rows": ["sales_rep"],
  "measures": ["total_revenue", "order_count", "avg_order_value"],
  "order_by": "-total_revenue",
  "limit": 10
}
```

---

## Best Practices

### 1. Dimension Design

- Use meaningful, business-friendly names
- Define hierarchies for drill-down support
- Limit cardinality for better performance

### 2. Measure Optimization

- Pre-aggregate common calculations
- Use appropriate data types
- Handle NULL values explicitly

### 3. Query Performance

- Add indexes on dimension columns
- Partition large datasets by date
- Use materialized views for common queries

### 4. Data Quality

- Validate dimension values
- Handle missing data consistently
- Document data lineage

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Slow queries | Large dataset | Add indexes, use partitioning |
| Missing data | NULL handling | Use COALESCE or filters |
| Wrong totals | Duplicate joins | Check join conditions |
| Memory errors | Large result set | Add LIMIT, use pagination |

### Debug Mode

```json
{
  "debug": {
    "show_sql": true,
    "explain_query": true,
    "log_execution_time": true
  }
}
```

---

*SAJHA MCP Server v2.9.8 - OLAP Tool Creator Guide*
*Copyright © 2025-2030 Ashutosh Sinha*
