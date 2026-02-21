# MCP Studio PowerBI DAX Query Tool Creator Guide
## SAJHA MCP Server v2.9.8

## Overview

The PowerBI DAX Query Tool Creator enables you to create MCP tools that execute Data Analysis Expressions (DAX) queries against Power BI datasets. This visual interface guides you through configuring DAX query execution, parameter binding, result formatting, and advanced analytics integration.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Understanding DAX Tools](#understanding-dax-tools)
3. [Creating Your First DAX Tool](#creating-your-first-dax-tool)
4. [DAX Query Configuration](#dax-query-configuration)
5. [Parameter Binding](#parameter-binding)
6. [Result Handling](#result-handling)
7. [Query Optimization](#query-optimization)
8. [Security Configuration](#security-configuration)
9. [Best Practices](#best-practices)
10. [Examples](#examples)
11. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Accessing the DAX Query Tool Creator

1. Navigate to `http://localhost:3002/admin/studio`
2. Click on **PowerBI DAX Query Tool** card
3. Or directly access: `http://localhost:3002/admin/studio/powerbidax`

### Prerequisites

- Admin role access to SAJHA MCP Server
- Microsoft Azure Active Directory app registration
- PowerBI Pro or Premium capacity
- Dataset with XMLA endpoint access (Premium only for some features)
- Understanding of DAX query language

### XMLA Endpoint Requirements

For advanced DAX queries, enable XMLA endpoints:

1. Go to Power BI Admin Portal
2. Navigate to Capacity settings
3. Enable XMLA read/write under Dataset workload settings
4. Ensure the dataset is in a Premium workspace

---

## Understanding DAX Tools

DAX query tools enable sophisticated analytical queries against Power BI datasets. When a DAX tool is invoked:

1. The tool receives query parameters from the MCP client
2. Substitutes parameters into the DAX query template
3. Authenticates with Power BI
4. Executes the DAX query against the dataset
5. Formats and returns the results

### Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌─────────────┐
│  MCP Client │────▶│  DAX Tool    │────▶│  PowerBI API    │────▶│  Dataset    │
│  (Claude)   │◀────│  (SAJHA)     │◀────│  Execute Query  │◀────│  Engine     │
└─────────────┘     └──────────────┘     └─────────────────┘     └─────────────┘
```

### DAX Query Types

| Type | Description | Use Case |
|------|-------------|----------|
| **Table Query** | Returns tabular data | Reports, data export |
| **Scalar Query** | Returns single value | KPIs, metrics |
| **Measure Query** | Evaluates measures | Calculations |
| **Table Constructor** | Creates inline tables | Parameterized queries |

---

## Creating Your First DAX Tool

### Step 1: Basic Information

Fill in the essential tool details:

| Field | Description | Example |
|-------|-------------|---------|
| **Tool Name** | Unique identifier (snake_case) | `sales_analysis_dax` |
| **Display Name** | Human-readable name | `Sales Analysis Query` |
| **Description** | What the tool does | `Analyze sales by region and product` |
| **Category** | Tool grouping | `Business Intelligence` |
| **Version** | Semantic version | `1.0.0` |

### Step 2: Dataset Configuration

Configure the target dataset:

```
Workspace ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Dataset ID: yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy
```

### Step 3: DAX Query

Write your DAX query:

```dax
EVALUATE
SUMMARIZECOLUMNS(
    'Date'[Year],
    'Product'[Category],
    "Total Sales", SUM(Sales[Amount]),
    "Order Count", COUNTROWS(Sales)
)
ORDER BY 'Date'[Year] DESC
```

### Step 4: Deploy

Click **Deploy Tool** to create and register the tool.

---

## DAX Query Configuration

### Basic Configuration

```json
{
  "name": "my_dax_tool",
  "implementation": "sajha.tools.impl.powerbi_dax_tool.PowerBIDAXTool",
  "version": "2.9.8",
  "enabled": true,
  "powerbi": {
    "workspace_id": "${powerbi.workspace.id}",
    "dataset_id": "${powerbi.dataset.id}",
    "tenant_id": "${azure.tenant.id}",
    "client_id": "${powerbi.client.id}",
    "client_secret": "${powerbi.client.secret}"
  },
  "query": {
    "type": "dax",
    "template": "EVALUATE SUMMARIZECOLUMNS(...)"
  }
}
```

### Query Templates with Parameters

```json
{
  "query": {
    "type": "dax",
    "template": "EVALUATE FILTER('Sales', 'Sales'[Year] = @year AND 'Sales'[Region] = \"@region\")",
    "parameters": {
      "year": {"type": "integer", "required": true},
      "region": {"type": "string", "required": true}
    }
  }
}
```

### Multiple Query Support

```json
{
  "queries": [
    {
      "name": "sales_summary",
      "template": "EVALUATE SUMMARIZECOLUMNS(...)"
    },
    {
      "name": "top_products",
      "template": "EVALUATE TOPN(10, ...)"
    }
  ],
  "query_selection": "parameter"
}
```

---

## Parameter Binding

### Parameter Types

| Type | DAX Format | Example |
|------|------------|---------|
| `integer` | `@param` | `'Sales'[Year] = @year` |
| `string` | `"@param"` | `'Sales'[Region] = "@region"` |
| `date` | `DATE(@y,@m,@d)` | `DATE(@year, @month, 1)` |
| `decimal` | `@param` | `'Sales'[Amount] > @threshold` |
| `list` | Custom handling | `IN {"@item1", "@item2"}` |

### Input Schema

```json
{
  "inputSchema": {
    "type": "object",
    "properties": {
      "year": {
        "type": "integer",
        "minimum": 2000,
        "maximum": 2030,
        "required": true,
        "description": "Analysis year"
      },
      "region": {
        "type": "string",
        "enum": ["North", "South", "East", "West"],
        "required": true,
        "description": "Sales region"
      },
      "top_n": {
        "type": "integer",
        "default": 10,
        "minimum": 1,
        "maximum": 100,
        "description": "Number of top results"
      },
      "include_forecast": {
        "type": "boolean",
        "default": false,
        "description": "Include forecast data"
      }
    }
  }
}
```

### Dynamic Query Building

```json
{
  "query": {
    "type": "dax",
    "dynamic": true,
    "base_template": "EVALUATE SUMMARIZECOLUMNS(@dimensions, @measures)",
    "dimension_mapping": {
      "by_year": "'Date'[Year]",
      "by_month": "'Date'[Month]",
      "by_category": "'Product'[Category]",
      "by_region": "'Geography'[Region]"
    },
    "measure_mapping": {
      "total_sales": "\"Total Sales\", SUM(Sales[Amount])",
      "order_count": "\"Orders\", COUNTROWS(Sales)",
      "avg_order": "\"Avg Order\", AVERAGE(Sales[Amount])"
    }
  },
  "inputSchema": {
    "properties": {
      "dimensions": {
        "type": "array",
        "items": {"type": "string", "enum": ["by_year", "by_month", "by_category", "by_region"]}
      },
      "measures": {
        "type": "array",
        "items": {"type": "string", "enum": ["total_sales", "order_count", "avg_order"]}
      }
    }
  }
}
```

### Date Range Parameters

```json
{
  "query": {
    "template": "EVALUATE CALCULATETABLE('Sales', 'Date'[Date] >= DATE(@start_year, @start_month, @start_day) && 'Date'[Date] <= DATE(@end_year, @end_month, @end_day))"
  },
  "parameter_conversion": {
    "start_date": {
      "type": "date",
      "extract": ["start_year", "start_month", "start_day"]
    },
    "end_date": {
      "type": "date",
      "extract": ["end_year", "end_month", "end_day"]
    }
  }
}
```

---

## Result Handling

### Output Schema

```json
{
  "outputSchema": {
    "type": "object",
    "properties": {
      "success": {"type": "boolean"},
      "row_count": {"type": "integer"},
      "columns": {
        "type": "array",
        "items": {"type": "string"}
      },
      "data": {
        "type": "array",
        "items": {"type": "object"}
      },
      "execution_time_ms": {"type": "integer"}
    }
  }
}
```

### Result Transformation

```json
{
  "result_transform": {
    "format": "records",
    "rename_columns": {
      "[Year]": "Year",
      "[Category]": "Category",
      "[Total Sales]": "TotalSales"
    },
    "numeric_precision": 2,
    "date_format": "YYYY-MM-DD"
  }
}
```

### Aggregation Options

```json
{
  "post_processing": {
    "sort_by": ["Year", "TotalSales"],
    "sort_order": ["asc", "desc"],
    "limit": 100,
    "add_totals": true,
    "calculate_percentages": ["TotalSales"]
  }
}
```

### Pagination

```json
{
  "pagination": {
    "enabled": true,
    "page_size": 100,
    "max_pages": 10
  }
}
```

---

## Query Optimization

### Query Hints

```json
{
  "optimization": {
    "use_query_cache": true,
    "query_timeout_seconds": 300,
    "max_rows": 10000,
    "allow_native_query": true
  }
}
```

### Efficient DAX Patterns

**Good - Using Variables:**
```dax
EVALUATE
VAR TotalSales = CALCULATE(SUM(Sales[Amount]))
VAR AvgSales = CALCULATE(AVERAGE(Sales[Amount]))
RETURN
ROW("Total", TotalSales, "Average", AvgSales, "Ratio", DIVIDE(TotalSales, AvgSales))
```

**Good - Using SUMMARIZECOLUMNS:**
```dax
EVALUATE
SUMMARIZECOLUMNS(
    'Date'[Year],
    'Product'[Category],
    TREATAS({@year}, 'Date'[Year]),
    "Total", SUM(Sales[Amount])
)
```

**Avoid - Nested Iterators:**
```dax
-- Avoid this pattern when possible
EVALUATE
ADDCOLUMNS(
    'Product',
    "ComplexCalc", SUMX(RELATEDTABLE(Sales), Sales[Amount] * Sales[Quantity])
)
```

### Caching Configuration

```json
{
  "caching": {
    "enabled": true,
    "ttl_seconds": 300,
    "cache_key_params": ["year", "region"],
    "invalidate_on_refresh": true
  }
}
```

---

## Security Configuration

### Row-Level Security

```json
{
  "security": {
    "rls_enabled": true,
    "effective_identity": {
      "username": "${rls.username}",
      "roles": ["SalesRep"],
      "datasets": ["${powerbi.dataset.id}"]
    }
  }
}
```

### Query Restrictions

```json
{
  "security": {
    "allowed_tables": ["Sales", "Product", "Date", "Geography"],
    "blocked_tables": ["Employee", "Salary", "HR"],
    "max_result_rows": 10000,
    "audit_queries": true
  }
}
```

### Input Sanitization

```json
{
  "security": {
    "sanitize_inputs": true,
    "escape_strings": true,
    "validate_identifiers": true,
    "block_injection_patterns": [
      "EVALUATE.*DROP",
      "ALTER.*TABLE",
      "CREATE.*TABLE"
    ]
  }
}
```

---

## Best Practices

### 1. Query Design

- Use variables for repeated expressions
- Prefer SUMMARIZECOLUMNS over ADDCOLUMNS + GROUPBY
- Filter early in the query
- Avoid unnecessary columns in results

### 2. Parameter Handling

- Always validate and sanitize inputs
- Use typed parameters
- Provide sensible defaults
- Document parameter constraints

### 3. Error Handling

```json
{
  "error_handling": {
    "retry_on_timeout": true,
    "max_retries": 3,
    "fallback_query": "EVALUATE ROW(\"Error\", TRUE())",
    "include_error_details": false
  }
}
```

### 4. Performance

- Set appropriate timeouts
- Use caching for repeated queries
- Limit result sets
- Monitor query execution times

### 5. Documentation

- Document query purpose
- Explain parameters
- Provide usage examples
- Note performance considerations

---

## Examples

### Example 1: Sales Summary by Year

```json
{
  "name": "sales_summary_by_year",
  "description": "Get sales summary grouped by year",
  "powerbi": {
    "workspace_id": "${powerbi.workspace.id}",
    "dataset_id": "${powerbi.dataset.id}"
  },
  "query": {
    "template": "EVALUATE\nSUMMARIZECOLUMNS(\n    'Date'[Year],\n    \"Total Sales\", SUM(Sales[Amount]),\n    \"Order Count\", COUNTROWS(Sales),\n    \"Avg Order Value\", AVERAGE(Sales[Amount])\n)\nORDER BY 'Date'[Year] DESC"
  },
  "inputSchema": {
    "type": "object",
    "properties": {}
  }
}
```

### Example 2: Top N Products with Filters

```json
{
  "name": "top_products_by_sales",
  "description": "Get top N products by sales for a specific year and region",
  "query": {
    "template": "EVALUATE\nTOPN(\n    @top_n,\n    SUMMARIZECOLUMNS(\n        'Product'[ProductName],\n        'Product'[Category],\n        TREATAS({@year}, 'Date'[Year]),\n        TREATAS({\"@region\"}, 'Geography'[Region]),\n        \"TotalSales\", SUM(Sales[Amount]),\n        \"UnitsSold\", SUM(Sales[Quantity])\n    ),\n    [TotalSales], DESC\n)"
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "year": {
        "type": "integer",
        "required": true,
        "description": "Filter year"
      },
      "region": {
        "type": "string",
        "required": true,
        "description": "Filter region"
      },
      "top_n": {
        "type": "integer",
        "default": 10,
        "minimum": 1,
        "maximum": 100,
        "description": "Number of top products"
      }
    }
  }
}
```

### Example 3: Year-over-Year Comparison

```json
{
  "name": "yoy_comparison",
  "description": "Compare metrics year-over-year",
  "query": {
    "template": "EVALUATE\nVAR CurrentYear = @year\nVAR PreviousYear = @year - 1\nVAR CurrentSales = CALCULATE(SUM(Sales[Amount]), 'Date'[Year] = CurrentYear)\nVAR PreviousSales = CALCULATE(SUM(Sales[Amount]), 'Date'[Year] = PreviousYear)\nVAR Growth = DIVIDE(CurrentSales - PreviousSales, PreviousSales)\nRETURN\nROW(\n    \"Current Year\", CurrentYear,\n    \"Current Sales\", CurrentSales,\n    \"Previous Year\", PreviousYear,\n    \"Previous Sales\", PreviousSales,\n    \"Growth Rate\", Growth\n)"
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "year": {
        "type": "integer",
        "required": true,
        "description": "Year to compare"
      }
    }
  }
}
```

### Example 4: Dynamic Dimension Query

```json
{
  "name": "dynamic_analysis",
  "description": "Analyze data with dynamic dimensions and measures",
  "query": {
    "dynamic": true,
    "base_template": "EVALUATE\nSUMMARIZECOLUMNS(\n    @dimensions,\n    @measures\n)\nORDER BY @sort_column @sort_order"
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "group_by": {
        "type": "array",
        "items": {
          "type": "string",
          "enum": ["year", "month", "quarter", "category", "region", "customer"]
        },
        "required": true,
        "description": "Dimensions to group by"
      },
      "metrics": {
        "type": "array",
        "items": {
          "type": "string",
          "enum": ["total_sales", "order_count", "avg_order", "unique_customers"]
        },
        "required": true,
        "description": "Metrics to calculate"
      },
      "sort_by": {
        "type": "string",
        "default": "total_sales",
        "description": "Column to sort by"
      },
      "sort_descending": {
        "type": "boolean",
        "default": true
      }
    }
  }
}
```

### Example 5: Time Intelligence Query

```json
{
  "name": "time_intelligence_metrics",
  "description": "Calculate time intelligence metrics (MTD, QTD, YTD)",
  "query": {
    "template": "EVALUATE\nVAR SelectedDate = DATE(@year, @month, @day)\nRETURN\nROW(\n    \"Date\", SelectedDate,\n    \"MTD Sales\", CALCULATE(SUM(Sales[Amount]), DATESMTD('Date'[Date])),\n    \"QTD Sales\", CALCULATE(SUM(Sales[Amount]), DATESQTD('Date'[Date])),\n    \"YTD Sales\", CALCULATE(SUM(Sales[Amount]), DATESYTD('Date'[Date])),\n    \"Same Period Last Year\", CALCULATE(SUM(Sales[Amount]), SAMEPERIODLASTYEAR('Date'[Date]))\n)"
  },
  "inputSchema": {
    "type": "object",
    "properties": {
      "year": {"type": "integer", "required": true},
      "month": {"type": "integer", "minimum": 1, "maximum": 12, "required": true},
      "day": {"type": "integer", "minimum": 1, "maximum": 31, "required": true}
    }
  }
}
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Authentication failed | Invalid credentials | Check tenant/client IDs and secrets |
| Dataset not found | Wrong dataset ID | Verify workspace and dataset IDs |
| Query timeout | Complex query | Optimize DAX or increase timeout |
| Invalid column | Column doesn't exist | Check column names in dataset |
| RLS not working | Incorrect identity | Verify effective identity configuration |
| Empty results | Filter too restrictive | Check filter parameters |

### Debug Checklist

1. ✅ Verify Azure AD app registration
2. ✅ Check API permissions are granted
3. ✅ Confirm dataset is accessible
4. ✅ Test DAX query in Power BI Desktop first
5. ✅ Validate parameter substitution
6. ✅ Check server logs for errors

### DAX Query Validation

Test your DAX query in Power BI Desktop:

1. Open Power BI Desktop
2. Connect to the same dataset
3. Open DAX Query View (View → DAX Query)
4. Paste your query and execute
5. Verify results match expectations

### Log Analysis

```bash
# View DAX query execution logs
tail -f logs/sajha_mcp.log | grep "PowerBIDAX"

# Check authentication issues
grep "token" logs/sajha_mcp.log | tail -20
```

### Common DAX Errors

| Error | Cause | Fix |
|-------|-------|-----|
| "Column not found" | Invalid column reference | Check table and column names |
| "Circular dependency" | Measure references itself | Review measure logic |
| "Type mismatch" | Wrong data type in filter | Cast or convert types |
| "EVALUATE missing" | Query syntax error | Ensure EVALUATE keyword present |

---

## Related Documentation

- [MCP Studio Overview](MCP_Studio_User_Guide.md)
- [PowerBI Tool Guide](MCP_Studio_PowerBI_Tool_Creator_Guide.md)
- [OLAP Analytics Guide](MCP_Studio_OLAP_Tool_Creator_Guide.md)

---

*SAJHA MCP Server v2.9.8 - PowerBI DAX Query Tool Creator Guide*
*Copyright © 2025-2030 Ashutosh Sinha*
