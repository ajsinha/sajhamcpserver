# MCP Studio PowerBI Tool Creator Guide
## SAJHA MCP Server v2.9.8

## Overview

The PowerBI Tool Creator enables you to create MCP tools that interact with Microsoft Power BI, allowing AI assistants to query reports, execute DAX queries, refresh datasets, and retrieve analytics data. Build powerful business intelligence integrations without complex API coding.

## Table of Contents

1. [Getting Started](#getting-started)
2. [PowerBI Authentication](#powerbi-authentication)
3. [Report Tool Creation](#report-tool-creation)
4. [DAX Query Tools](#dax-query-tools)
5. [Dataset Operations](#dataset-operations)
6. [Dashboard Integration](#dashboard-integration)
7. [Embedded Analytics](#embedded-analytics)
8. [Security Configuration](#security-configuration)
9. [Examples](#examples)
10. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Accessing the PowerBI Tool Creator

1. Navigate to `http://localhost:3002/admin/studio`
2. Click on **PowerBI Report Tool** or **PowerBI DAX Query Tool** card
3. Or directly access:
   - Report Tool: `http://localhost:3002/admin/studio/powerbi`
   - DAX Query Tool: `http://localhost:3002/admin/studio/powerbidax`

### Prerequisites

- Admin role access to SAJHA MCP Server
- Microsoft Azure Active Directory app registration
- PowerBI Pro or Premium capacity
- Appropriate PowerBI workspace access

### Azure App Registration

1. Go to Azure Portal → Azure Active Directory → App registrations
2. Create new registration
3. Add API permissions:
   - `Power BI Service` → `Dataset.Read.All`
   - `Power BI Service` → `Report.Read.All`
   - `Power BI Service` → `Dashboard.Read.All`
   - `Power BI Service` → `Workspace.Read.All`
4. Create client secret
5. Note: Application (client) ID, Directory (tenant) ID, Client Secret

---

## PowerBI Authentication

### Service Principal Authentication

```json
{
  "authentication": {
    "type": "service_principal",
    "tenant_id": "${azure.tenant.id}",
    "client_id": "${powerbi.client.id}",
    "client_secret": "${powerbi.client.secret}",
    "scope": "https://analysis.windows.net/powerbi/api/.default"
  }
}
```

### User Authentication (Interactive)

```json
{
  "authentication": {
    "type": "user_auth",
    "tenant_id": "${azure.tenant.id}",
    "client_id": "${powerbi.client.id}",
    "redirect_uri": "http://localhost:3002/auth/callback"
  }
}
```

### Master User Authentication

```json
{
  "authentication": {
    "type": "master_user",
    "tenant_id": "${azure.tenant.id}",
    "client_id": "${powerbi.client.id}",
    "username": "${powerbi.master.user}",
    "password": "${powerbi.master.password}"
  }
}
```

### Store Credentials in application.properties

```properties
# Azure AD Configuration
azure.tenant.id=${AZURE_TENANT_ID}

# PowerBI App Registration
powerbi.client.id=${POWERBI_CLIENT_ID}
powerbi.client.secret=${POWERBI_CLIENT_SECRET}

# PowerBI Workspace
powerbi.workspace.id=${POWERBI_WORKSPACE_ID}
```

---

## Report Tool Creation

### Basic Report Tool Configuration

```json
{
  "name": "powerbi_sales_report",
  "display_name": "Sales Report Query",
  "description": "Query sales data from PowerBI report",
  "category": "Business Intelligence",
  "version": "2.9.8",
  "implementation": "sajha.tools.impl.powerbi_tool.PowerBIReportTool",
  "workspace_id": "${powerbi.workspace.id}",
  "report_id": "${powerbi.sales.report.id}"
}
```

### Report Operations

```json
{
  "operations": {
    "get_pages": {
      "description": "List all pages in the report"
    },
    "get_visuals": {
      "description": "List visuals on a specific page",
      "parameters": {
        "page_name": {"type": "string", "required": true}
      }
    },
    "export_data": {
      "description": "Export data from a visual",
      "parameters": {
        "page_name": {"type": "string", "required": true},
        "visual_name": {"type": "string", "required": true},
        "rows": {"type": "integer", "default": 1000}
      }
    },
    "apply_filters": {
      "description": "Apply filters and get data",
      "parameters": {
        "filters": {"type": "array"}
      }
    }
  }
}
```

### Input Schema for Report Tool

```json
{
  "inputSchema": {
    "type": "object",
    "properties": {
      "operation": {
        "type": "string",
        "enum": ["get_pages", "get_visuals", "export_data", "apply_filters"],
        "required": true
      },
      "page_name": {
        "type": "string",
        "description": "Report page name"
      },
      "visual_name": {
        "type": "string",
        "description": "Visual title or name"
      },
      "filters": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "table": {"type": "string"},
            "column": {"type": "string"},
            "operator": {"type": "string", "enum": ["eq", "ne", "gt", "lt", "contains", "in"]},
            "value": {}
          }
        }
      },
      "export_format": {
        "type": "string",
        "enum": ["json", "csv", "excel"],
        "default": "json"
      }
    }
  }
}
```

---

## DAX Query Tools

### DAX Query Tool Configuration

```json
{
  "name": "powerbi_dax_query",
  "display_name": "PowerBI DAX Query",
  "description": "Execute DAX queries against PowerBI datasets",
  "category": "Business Intelligence",
  "version": "2.9.8",
  "implementation": "sajha.tools.impl.powerbi_dax_tool.PowerBIDAXTool",
  "workspace_id": "${powerbi.workspace.id}",
  "dataset_id": "${powerbi.dataset.id}"
}
```

### DAX Query Input Schema

```json
{
  "inputSchema": {
    "type": "object",
    "properties": {
      "dax_query": {
        "type": "string",
        "required": true,
        "description": "DAX query to execute"
      },
      "parameters": {
        "type": "object",
        "description": "Query parameters"
      },
      "timeout_seconds": {
        "type": "integer",
        "default": 120,
        "maximum": 600
      }
    }
  }
}
```

### Example DAX Queries

**Basic Aggregation:**
```dax
EVALUATE
SUMMARIZECOLUMNS(
    'Date'[Year],
    'Product'[Category],
    "Total Sales", SUM('Sales'[Amount]),
    "Order Count", COUNTROWS('Sales')
)
ORDER BY 'Date'[Year], [Total Sales] DESC
```

**Time Intelligence:**
```dax
EVALUATE
VAR CurrentYearSales = CALCULATE(SUM('Sales'[Amount]), YEAR('Date'[Date]) = 2024)
VAR PriorYearSales = CALCULATE(SUM('Sales'[Amount]), YEAR('Date'[Date]) = 2023)
RETURN
ROW(
    "Current Year Sales", CurrentYearSales,
    "Prior Year Sales", PriorYearSales,
    "YoY Growth", DIVIDE(CurrentYearSales - PriorYearSales, PriorYearSales, 0)
)
```

**Top N Analysis:**
```dax
EVALUATE
TOPN(
    10,
    SUMMARIZECOLUMNS(
        'Customer'[CustomerName],
        "Total Revenue", SUM('Sales'[Amount])
    ),
    [Total Revenue], DESC
)
```

### Predefined Query Templates

```json
{
  "query_templates": {
    "sales_by_region": {
      "dax": "EVALUATE SUMMARIZECOLUMNS('Geography'[Region], \"Sales\", SUM('Sales'[Amount]))",
      "description": "Sales aggregated by region"
    },
    "monthly_trend": {
      "dax": "EVALUATE SUMMARIZECOLUMNS('Date'[YearMonth], \"Sales\", SUM('Sales'[Amount])) ORDER BY 'Date'[YearMonth]",
      "description": "Monthly sales trend"
    },
    "top_products": {
      "dax": "EVALUATE TOPN(${limit}, SUMMARIZECOLUMNS('Product'[ProductName], \"Sales\", SUM('Sales'[Amount])), [Sales], DESC)",
      "parameters": {"limit": {"type": "integer", "default": 10}}
    }
  }
}
```

---

## Dataset Operations

### Dataset Refresh Tool

```json
{
  "name": "powerbi_dataset_refresh",
  "description": "Trigger dataset refresh in PowerBI",
  "operations": {
    "refresh": {
      "description": "Start dataset refresh",
      "parameters": {
        "notify_option": {"type": "string", "enum": ["NoNotification", "MailOnFailure", "MailOnCompletion"]}
      }
    },
    "get_refresh_history": {
      "description": "Get refresh history",
      "parameters": {
        "limit": {"type": "integer", "default": 10}
      }
    },
    "get_refresh_status": {
      "description": "Check current refresh status"
    }
  }
}
```

### Dataset Information Tool

```json
{
  "name": "powerbi_dataset_info",
  "description": "Get dataset metadata and schema",
  "operations": {
    "get_tables": "List all tables in dataset",
    "get_columns": "Get columns for a specific table",
    "get_measures": "List all DAX measures",
    "get_relationships": "Get table relationships"
  }
}
```

---

## Dashboard Integration

### Dashboard Tool Configuration

```json
{
  "name": "powerbi_dashboard",
  "description": "Interact with PowerBI dashboards",
  "operations": {
    "list_dashboards": {
      "description": "List all dashboards in workspace"
    },
    "get_tiles": {
      "description": "Get tiles from a dashboard",
      "parameters": {
        "dashboard_id": {"type": "string", "required": true}
      }
    },
    "get_tile_data": {
      "description": "Get data from a specific tile",
      "parameters": {
        "dashboard_id": {"type": "string", "required": true},
        "tile_id": {"type": "string", "required": true}
      }
    }
  }
}
```

---

## Embedded Analytics

### Embed Token Generation

```json
{
  "name": "powerbi_embed_token",
  "description": "Generate embed tokens for PowerBI embedding",
  "inputSchema": {
    "type": "object",
    "properties": {
      "resource_type": {
        "type": "string",
        "enum": ["report", "dashboard", "dataset", "tile"],
        "required": true
      },
      "resource_id": {
        "type": "string",
        "required": true
      },
      "access_level": {
        "type": "string",
        "enum": ["View", "Edit", "Create"],
        "default": "View"
      },
      "expiration_hours": {
        "type": "integer",
        "default": 1,
        "maximum": 24
      }
    }
  }
}
```

---

## Security Configuration

### Row-Level Security (RLS)

```json
{
  "security": {
    "rls_enabled": true,
    "effective_identity": {
      "username": "${current.user.email}",
      "roles": ["SalesRegion"],
      "datasets": ["${powerbi.dataset.id}"]
    }
  }
}
```

### Workspace Access Control

```json
{
  "access_control": {
    "allowed_workspaces": ["${powerbi.workspace.id}"],
    "allowed_operations": ["read", "export"],
    "blocked_operations": ["delete", "modify"],
    "audit_logging": true
  }
}
```

---

## Examples

### Example 1: Sales Dashboard Query Tool

```json
{
  "name": "sales_dashboard_query",
  "description": "Query sales data from PowerBI dashboard",
  "version": "2.9.8",
  "workspace_id": "${powerbi.workspace.id}",
  "dataset_id": "${powerbi.sales.dataset.id}",
  "predefined_queries": {
    "daily_sales": {
      "dax": "EVALUATE SUMMARIZECOLUMNS('Date'[Date], \"Sales\", SUM('Sales'[Amount])) ORDER BY 'Date'[Date] DESC",
      "cache_ttl": 300
    },
    "regional_performance": {
      "dax": "EVALUATE SUMMARIZECOLUMNS('Geography'[Region], 'Geography'[Country], \"Sales\", SUM('Sales'[Amount]), \"Orders\", COUNTROWS('Sales'))",
      "cache_ttl": 600
    },
    "product_ranking": {
      "dax": "EVALUATE TOPN(20, SUMMARIZECOLUMNS('Product'[ProductName], 'Product'[Category], \"Revenue\", SUM('Sales'[Amount])), [Revenue], DESC)"
    }
  }
}
```

### Example 2: Financial Reporting Tool

```json
{
  "name": "financial_report_tool",
  "description": "Financial analytics and reporting",
  "version": "2.9.8",
  "operations": {
    "income_statement": {
      "dax": "EVALUATE VAR Revenue = CALCULATE(SUM('Finance'[Amount]), 'Finance'[Type] = \"Revenue\") VAR Expenses = CALCULATE(SUM('Finance'[Amount]), 'Finance'[Type] = \"Expense\") RETURN ROW(\"Revenue\", Revenue, \"Expenses\", Expenses, \"Net Income\", Revenue - Expenses)"
    },
    "cash_flow": {
      "dax": "EVALUATE SUMMARIZECOLUMNS('Date'[Month], 'Finance'[Category], \"Amount\", SUM('Finance'[Amount])) ORDER BY 'Date'[Month]"
    },
    "budget_variance": {
      "dax": "EVALUATE SUMMARIZECOLUMNS('Department'[Name], \"Actual\", SUM('Finance'[Actual]), \"Budget\", SUM('Finance'[Budget]), \"Variance\", SUM('Finance'[Actual]) - SUM('Finance'[Budget]))"
    }
  }
}
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| 401 Unauthorized | Invalid credentials | Check app registration and secrets |
| 403 Forbidden | Insufficient permissions | Add required API permissions |
| Dataset not found | Wrong workspace/dataset ID | Verify IDs in PowerBI service |
| DAX syntax error | Invalid query | Test query in PowerBI Desktop first |
| Timeout | Large dataset | Optimize DAX, add filters |

### Debug Configuration

```json
{
  "debug": {
    "log_requests": true,
    "log_responses": false,
    "log_dax_queries": true,
    "capture_metrics": true
  }
}
```

### Testing Connection

```bash
# Test PowerBI API access
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://api.powerbi.com/v1.0/myorg/groups"
```

---

*SAJHA MCP Server v2.9.8 - PowerBI Tool Creator Guide*
*Copyright © 2025-2030 Ashutosh Sinha*
