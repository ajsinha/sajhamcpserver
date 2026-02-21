# MCP Studio Database Query Tool Creator Guide
## SAJHA MCP Server v2.9.8

## Overview

The Database Query Tool Creator enables you to create MCP tools that execute SQL queries against various databases including PostgreSQL, MySQL, SQL Server, Oracle, SQLite, and DuckDB. Build powerful data retrieval and analytics tools without writing driver-level code.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Supported Databases](#supported-databases)
3. [Creating Database Tools](#creating-database-tools)
4. [Connection Configuration](#connection-configuration)
5. [Query Configuration](#query-configuration)
6. [Parameter Handling](#parameter-handling)
7. [Result Processing](#result-processing)
8. [Security Best Practices](#security-best-practices)
9. [Performance Optimization](#performance-optimization)
10. [Examples](#examples)
11. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Accessing the Database Query Tool Creator

1. Navigate to `http://localhost:3002/admin/studio`
2. Click on **Database Query Tool** card
3. Or directly access: `http://localhost:3002/admin/studio/dbquery`

### Prerequisites

- Admin role access to SAJHA MCP Server
- Database connection credentials
- Database driver installed
- Network access to database server

---

## Supported Databases

| Database | Driver | Connection String Format |
|----------|--------|-------------------------|
| **PostgreSQL** | psycopg2 | `postgresql://user:pass@host:5432/db` |
| **MySQL** | pymysql | `mysql://user:pass@host:3306/db` |
| **SQL Server** | pyodbc | `mssql+pyodbc://user:pass@host/db` |
| **Oracle** | cx_Oracle | `oracle://user:pass@host:1521/sid` |
| **SQLite** | sqlite3 | `sqlite:///path/to/db.sqlite` |
| **DuckDB** | duckdb | `duckdb:///path/to/db.duckdb` |

---

## Creating Database Tools

### Step 1: Basic Information

```json
{
  "name": "customer_sales_query",
  "display_name": "Customer Sales Query",
  "description": "Query customer sales data with filters",
  "category": "Sales Analytics",
  "version": "2.9.8"
}
```

### Step 2: Database Connection

```json
{
  "connection": {
    "type": "postgresql",
    "host": "${db.host}",
    "port": 5432,
    "database": "${db.name}",
    "username": "${db.user}",
    "password": "${db.password}",
    "ssl_mode": "require"
  }
}
```

### Step 3: Query Definition

```json
{
  "query": {
    "type": "select",
    "sql": "SELECT customer_id, customer_name, SUM(amount) as total_sales FROM sales WHERE region = :region AND sale_date >= :start_date GROUP BY customer_id, customer_name ORDER BY total_sales DESC LIMIT :limit",
    "parameters": {
      "region": {"type": "string", "required": true},
      "start_date": {"type": "date", "required": true},
      "limit": {"type": "integer", "default": 100}
    }
  }
}
```

### Step 4: Deploy

Click **Deploy Tool** to create and register the tool.

---

## Connection Configuration

### Connection String Method

```json
{
  "connection": {
    "connection_string": "${database.connection.string}",
    "pool_size": 5,
    "max_overflow": 10,
    "pool_timeout": 30
  }
}
```

### Individual Parameters Method

```json
{
  "connection": {
    "type": "postgresql",
    "host": "${db.host}",
    "port": "${db.port:5432}",
    "database": "${db.name}",
    "username": "${db.user}",
    "password": "${db.password}",
    "options": {
      "ssl_mode": "verify-full",
      "ssl_cert": "/path/to/cert.pem",
      "connect_timeout": 10,
      "application_name": "SAJHA-MCP"
    }
  }
}
```

### Connection Pooling

```json
{
  "connection": {
    "pooling": {
      "enabled": true,
      "min_connections": 2,
      "max_connections": 10,
      "idle_timeout": 300,
      "max_lifetime": 3600
    }
  }
}
```

### Multiple Database Support

```json
{
  "connections": {
    "primary": {
      "type": "postgresql",
      "connection_string": "${primary.db.url}"
    },
    "analytics": {
      "type": "duckdb",
      "connection_string": "${analytics.db.url}"
    },
    "archive": {
      "type": "mysql",
      "connection_string": "${archive.db.url}"
    }
  },
  "default_connection": "primary"
}
```

---

## Query Configuration

### Simple SELECT Query

```json
{
  "query": {
    "type": "select",
    "sql": "SELECT * FROM customers WHERE status = :status",
    "parameters": {
      "status": {"type": "string", "default": "active"}
    }
  }
}
```

### Parameterized Query with Validation

```json
{
  "query": {
    "sql": "SELECT product_name, quantity, price FROM inventory WHERE category = :category AND price BETWEEN :min_price AND :max_price ORDER BY :sort_by :sort_dir LIMIT :limit",
    "parameters": {
      "category": {
        "type": "string",
        "required": true,
        "enum": ["electronics", "clothing", "food", "furniture"]
      },
      "min_price": {
        "type": "number",
        "minimum": 0,
        "default": 0
      },
      "max_price": {
        "type": "number",
        "minimum": 0,
        "default": 999999
      },
      "sort_by": {
        "type": "string",
        "enum": ["product_name", "quantity", "price"],
        "default": "product_name"
      },
      "sort_dir": {
        "type": "string",
        "enum": ["ASC", "DESC"],
        "default": "ASC"
      },
      "limit": {
        "type": "integer",
        "minimum": 1,
        "maximum": 1000,
        "default": 100
      }
    }
  }
}
```

### Aggregate Query

```json
{
  "query": {
    "sql": "SELECT region, product_category, COUNT(*) as order_count, SUM(amount) as total_revenue, AVG(amount) as avg_order_value FROM orders WHERE order_date BETWEEN :start_date AND :end_date GROUP BY region, product_category HAVING SUM(amount) > :min_revenue ORDER BY total_revenue DESC",
    "parameters": {
      "start_date": {"type": "date", "required": true},
      "end_date": {"type": "date", "required": true},
      "min_revenue": {"type": "number", "default": 0}
    }
  }
}
```

### Dynamic SQL (Advanced)

```json
{
  "query": {
    "type": "dynamic",
    "template": "SELECT {{ columns | default('*') }} FROM {{ table }} WHERE 1=1 {% if status %}AND status = :status{% endif %} {% if region %}AND region = :region{% endif %} ORDER BY {{ order_by | default('id') }} LIMIT :limit",
    "parameters": {
      "table": {"type": "string", "required": true, "enum": ["customers", "orders", "products"]},
      "columns": {"type": "string"},
      "status": {"type": "string"},
      "region": {"type": "string"},
      "order_by": {"type": "string"},
      "limit": {"type": "integer", "default": 100}
    }
  }
}
```

### Stored Procedure Call

```json
{
  "query": {
    "type": "procedure",
    "name": "sp_generate_report",
    "parameters": {
      "report_type": {"type": "string", "required": true},
      "start_date": {"type": "date", "required": true},
      "end_date": {"type": "date", "required": true}
    },
    "output_parameters": ["result_count", "report_id"]
  }
}
```

---

## Parameter Handling

### Parameter Types

| Type | SQL Type | Example |
|------|----------|---------|
| `string` | VARCHAR | `"active"` |
| `integer` | INTEGER | `42` |
| `number` | DECIMAL | `19.99` |
| `boolean` | BOOLEAN | `true` |
| `date` | DATE | `"2024-01-15"` |
| `datetime` | TIMESTAMP | `"2024-01-15T10:30:00"` |
| `array` | Array | `["a", "b", "c"]` |
| `json` | JSONB | `{"key": "value"}` |

### Parameter Validation

```json
{
  "parameters": {
    "email": {
      "type": "string",
      "format": "email",
      "required": true
    },
    "quantity": {
      "type": "integer",
      "minimum": 1,
      "maximum": 1000
    },
    "status": {
      "type": "string",
      "enum": ["pending", "active", "completed", "cancelled"]
    },
    "tags": {
      "type": "array",
      "items": {"type": "string"},
      "minItems": 1,
      "maxItems": 10
    }
  }
}
```

### IN Clause Handling

```json
{
  "query": {
    "sql": "SELECT * FROM products WHERE category IN :categories",
    "parameters": {
      "categories": {
        "type": "array",
        "items": {"type": "string"},
        "expand_in_clause": true
      }
    }
  }
}
```

---

## Result Processing

### Column Mapping

```json
{
  "result": {
    "mapping": {
      "cust_id": "customer_id",
      "cust_name": "customer_name",
      "tot_amt": "total_amount"
    }
  }
}
```

### Data Transformation

```json
{
  "result": {
    "transforms": {
      "amount": {"type": "currency", "currency": "USD"},
      "created_at": {"type": "datetime", "format": "YYYY-MM-DD"},
      "status": {"type": "enum", "mapping": {"A": "Active", "I": "Inactive"}}
    }
  }
}
```

### Pagination

```json
{
  "result": {
    "pagination": {
      "enabled": true,
      "page_size": 50,
      "max_page_size": 500,
      "include_total_count": true
    }
  }
}
```

### Output Schema

```json
{
  "outputSchema": {
    "type": "object",
    "properties": {
      "success": {"type": "boolean"},
      "row_count": {"type": "integer"},
      "columns": {"type": "array", "items": {"type": "string"}},
      "data": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "customer_id": {"type": "string"},
            "customer_name": {"type": "string"},
            "total_sales": {"type": "number"}
          }
        }
      },
      "execution_time_ms": {"type": "number"}
    }
  }
}
```

---

## Security Best Practices

### 1. Parameterized Queries Only

**NEVER** use string concatenation:

```python
# BAD - SQL Injection vulnerable
query = f"SELECT * FROM users WHERE name = '{user_input}'"

# GOOD - Parameterized
query = "SELECT * FROM users WHERE name = :name"
params = {"name": user_input}
```

### 2. Credential Management

```json
{
  "connection": {
    "username": "${db.user}",
    "password": "${db.password}"
  }
}
```

Store credentials in `application.properties`:
```properties
db.user=${DB_USER}
db.password=${DB_PASSWORD}
```

### 3. Query Restrictions

```json
{
  "security": {
    "allowed_operations": ["SELECT"],
    "blocked_keywords": ["DROP", "DELETE", "TRUNCATE", "ALTER", "GRANT"],
    "max_rows": 10000,
    "query_timeout": 30
  }
}
```

### 4. Row-Level Security

```json
{
  "security": {
    "row_filter": "tenant_id = :current_tenant_id",
    "inject_user_context": true
  }
}
```

---

## Performance Optimization

### Query Hints

```json
{
  "query": {
    "sql": "SELECT /*+ INDEX(orders idx_order_date) */ * FROM orders WHERE order_date > :date",
    "hints": {
      "use_index": "idx_order_date",
      "parallel_degree": 4
    }
  }
}
```

### Caching

```json
{
  "caching": {
    "enabled": true,
    "ttl_seconds": 300,
    "cache_key_params": ["region", "date_range"],
    "invalidation_triggers": ["orders_table_update"]
  }
}
```

### Query Timeout

```json
{
  "query": {
    "timeout_seconds": 30,
    "cancel_on_timeout": true
  }
}
```

---

## Examples

### Example 1: Sales Dashboard Query

```json
{
  "name": "sales_dashboard_summary",
  "description": "Get sales summary for dashboard",
  "connection": {
    "type": "postgresql",
    "connection_string": "${sales.db.url}"
  },
  "query": {
    "sql": "SELECT DATE_TRUNC('day', order_date) as date, COUNT(*) as orders, SUM(amount) as revenue, AVG(amount) as avg_order FROM orders WHERE order_date >= :start_date AND order_date < :end_date GROUP BY DATE_TRUNC('day', order_date) ORDER BY date",
    "parameters": {
      "start_date": {"type": "date", "required": true},
      "end_date": {"type": "date", "required": true}
    }
  }
}
```

### Example 2: Customer Search

```json
{
  "name": "customer_search",
  "description": "Search customers by various criteria",
  "connection": {
    "type": "mysql",
    "connection_string": "${crm.db.url}"
  },
  "query": {
    "sql": "SELECT customer_id, name, email, phone, created_at FROM customers WHERE (name LIKE :search_term OR email LIKE :search_term) AND status = :status ORDER BY created_at DESC LIMIT :limit",
    "parameters": {
      "search_term": {"type": "string", "required": true},
      "status": {"type": "string", "default": "active"},
      "limit": {"type": "integer", "default": 50, "maximum": 200}
    }
  }
}
```

### Example 3: Inventory Report

```json
{
  "name": "inventory_report",
  "description": "Generate inventory status report",
  "connection": {
    "type": "sqlserver",
    "connection_string": "${inventory.db.url}"
  },
  "query": {
    "sql": "SELECT p.product_id, p.product_name, p.category, i.quantity_on_hand, i.reorder_point, CASE WHEN i.quantity_on_hand <= i.reorder_point THEN 'Low Stock' WHEN i.quantity_on_hand = 0 THEN 'Out of Stock' ELSE 'In Stock' END as stock_status FROM products p JOIN inventory i ON p.product_id = i.product_id WHERE p.category = :category OR :category IS NULL ORDER BY stock_status, p.product_name",
    "parameters": {
      "category": {"type": "string", "required": false}
    }
  }
}
```

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Connection refused | Wrong host/port | Verify connection settings |
| Authentication failed | Bad credentials | Check username/password |
| Query timeout | Slow query | Add indexes, optimize query |
| Too many connections | Pool exhausted | Increase pool size |
| Parameter type mismatch | Wrong data type | Check parameter types |

### Debug Mode

```json
{
  "debug": {
    "enabled": true,
    "log_queries": true,
    "log_parameters": false,
    "explain_analyze": true
  }
}
```

### Connection Testing

```bash
# Test PostgreSQL connection
psql -h hostname -U username -d database -c "SELECT 1"

# Test MySQL connection
mysql -h hostname -u username -p database -e "SELECT 1"
```

---

*SAJHA MCP Server v2.9.8 - Database Query Tool Creator Guide*
*Copyright © 2025-2030 Ashutosh Sinha*
