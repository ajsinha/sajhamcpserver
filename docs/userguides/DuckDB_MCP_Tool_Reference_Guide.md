# DuckDB MCP Tool Reference Guide

**Copyright © 2025-2030 Ashutosh Sinha. All rights reserved.**  
**Email:** ajsinha@gmail.com

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [System Requirements](#system-requirements)
4. [Installation & Setup](#installation--setup)
5. [Tool Details](#tool-details)
6. [API Reference](#api-reference)
7. [Sample Code](#sample-code)
8. [Schema Definitions](#schema-definitions)
9. [Limitations](#limitations)
10. [Troubleshooting](#troubleshooting)

---

## Overview

The DuckDB MCP (Model Context Protocol) Tool Suite provides a comprehensive set of analytical tools for performing OLAP (Online Analytical Processing) operations on structured data files. This toolkit leverages DuckDB, a high-performance analytical database engine, to enable SQL-based analytics on CSV, Parquet, JSON, and TSV files without requiring a traditional database server.

### Key Features

- **Zero-configuration Analytics**: Query data files directly without complex ETL processes
- **High Performance**: Optimized columnar storage and query execution
- **Multi-format Support**: Works with CSV, Parquet, JSON, and TSV files
- **SQL Compatibility**: Full SQL query support including complex joins and window functions
- **Simplified Operations**: Pre-built tools for common analytical tasks
- **No External Dependencies**: Self-contained with embedded DuckDB engine

### Use Cases

- Ad-hoc data analysis and exploration
- Business intelligence reporting
- Data quality assessment and profiling
- ETL validation and testing
- Research and statistical analysis
- Financial data analysis

---

## Architecture

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                      MCP Client Application                      │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 │ MCP Protocol
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│                    DuckDB MCP Tool Server                        │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              BaseMCPTool (Abstract Base)                  │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                           │                                      │
│  ┌────────────────────────▼─────────────────────────────────┐  │
│  │           DuckDbBaseTool (Shared Functionality)           │  │
│  │  • Connection Management                                  │  │
│  │  • Query Execution                                        │  │
│  │  • File System Operations                                 │  │
│  │  • Utility Functions                                      │  │
│  └────────────────────────┬─────────────────────────────────┘  │
│                           │                                      │
│         ┌─────────────────┴─────────────────┬─────────────┐    │
│         │                 │                 │             │    │
│  ┏━━━━━━▼━━━━━┓   ┏━━━━━━▼━━━━━┓   ┏━━━━━━▼━━━━━┓  ┏━━━━▼━━━┓│
│  ┃ListTables ┃   ┃  Describe  ┃   ┃   Query    ┃  ┃Get Stats┃│
│  ┃   Tool    ┃   ┃Table Tool  ┃   ┃    Tool    ┃  ┃  Tool   ┃│
│  ┗━━━━━━━━━━━┛   ┗━━━━━━━━━━━━┛   ┗━━━━━━━━━━━━┛  ┗━━━━━━━━━┛│
│                                                                  │
│  ┏━━━━━━━━━━━┓   ┏━━━━━━━━━━━━┓   ┏━━━━━━━━━━━━┓              │
│  ┃Aggregate  ┃   ┃List Files  ┃   ┃  Refresh   ┃              │
│  ┃   Tool    ┃   ┃   Tool     ┃   ┃Views Tool  ┃              │
│  ┗━━━━━━━━━━━┛   ┗━━━━━━━━━━━━┛   ┗━━━━━━━━━━━━┛              │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              │ SQL Queries
                              │
┌─────────────────────────────▼────────────────────────────────────┐
│                    DuckDB Engine (Embedded)                       │
│  • Query Parser & Optimizer                                       │
│  • Execution Engine                                               │
│  • Storage Manager                                                │
│  • Transaction Manager                                            │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              │ File I/O
                              │
┌─────────────────────────────▼────────────────────────────────────┐
│                      Data Directory                               │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │CSV Files │  │  Parquet │  │   JSON   │  │TSV Files │        │
│  │          │  │  Files   │  │  Files   │  │          │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
│                                                                   │
│  └─────────────── duckdb_analytics.db ──────────────┘           │
└───────────────────────────────────────────────────────────────────┘
```

### Component Overview

#### 1. **BaseMCPTool** (Abstract Base Class)
- Defines common interface for all MCP tools
- Provides logging, configuration management
- Standard execute() method signature

#### 2. **DuckDbBaseTool** (Shared Base Class)
Provides shared functionality for all DuckDB tools:
- **Connection Management**: Singleton connection pattern for efficiency
- **Query Execution**: Safe SQL execution with error handling
- **File System Operations**: Scanning, listing, and metadata extraction
- **Utility Functions**: File size formatting, type detection

#### 3. **Individual Tool Classes**
Each tool inherits from DuckDbBaseTool and implements specific functionality:
- Input/output schema definitions
- Business logic for specific operations
- Result formatting and validation

### Data Flow

```
User Request → MCP Protocol → Tool Selection → Input Validation
    ↓
Execute Method → DuckDB Connection → SQL Query Generation
    ↓
Query Execution → Result Processing → Output Formatting
    ↓
Response ← MCP Protocol ← Formatted Results
```

### Working Mechanism

**This toolkit performs LOCAL DATABASE QUERIES - No web scraping, crawling, or external API calls**

1. **File-Based Analytics**: Data files (CSV, Parquet, JSON, TSV) are stored in a designated data directory
2. **Embedded Database**: DuckDB maintains a local database file (`duckdb_analytics.db`) for metadata and query processing
3. **Direct File Querying**: DuckDB can query files directly without importing them into tables
4. **In-Memory Processing**: Query results are processed in memory for optimal performance
5. **ACID Compliance**: Full transaction support for data integrity

---

## System Requirements

### Software Requirements

- **Python**: 3.8 or higher
- **DuckDB**: 0.9.0 or higher
- **Operating System**: Linux, macOS, or Windows
- **Memory**: Minimum 2GB RAM (8GB+ recommended for large datasets)
- **Disk Space**: Varies based on data size (minimum 100MB)

### Python Dependencies

```python
duckdb >= 0.9.0
```

### Hardware Recommendations

| Dataset Size | RAM | CPU Cores | Storage |
|-------------|-----|-----------|---------|
| < 1 GB | 2 GB | 2 | 5 GB |
| 1-10 GB | 8 GB | 4 | 20 GB |
| 10-100 GB | 16 GB | 8 | 200 GB |
| > 100 GB | 32 GB+ | 16+ | 500 GB+ |

---

## Installation & Setup

### Step 1: Install DuckDB

```bash
# Using pip
pip install duckdb --break-system-packages

# Or with conda
conda install -c conda-forge duckdb
```

### Step 2: Configure Data Directory

```python
import os

# Create data directory
data_dir = "/path/to/your/data/duckdb"
os.makedirs(data_dir, exist_ok=True)
```

### Step 3: Initialize Tools

```python
from tools.impl.duckdb_olap_tools_refactored import DUCKDB_TOOLS

# Initialize all tools
config = {
    'data_directory': '/path/to/data/duckdb',
    'enabled': True
}

# Create tool instances
list_tables_tool = DUCKDB_TOOLS['duckdb_list_tables'](config)
query_tool = DUCKDB_TOOLS['duckdb_query'](config)
```

### Step 4: Verify Installation

```python
# Test connection
result = list_tables_tool.execute({})
print(f"Found {result['total_count']} tables")
```

### Authentication & API Keys

**NONE REQUIRED** - This toolkit operates entirely on local data and requires no external authentication or API keys.

---

## Tool Details

### 1. duckdb_list_tables

**Purpose**: List all available tables and views in the DuckDB database

**Operation Type**: Database metadata query

**Use Cases**:
- Discover available datasets
- Verify data loading
- Explore database structure

**Input Parameters**:
```json
{
  "include_system_tables": false  // Optional: Include system tables
}
```

**Output**:
```json
{
  "tables": [
    {
      "name": "sales_data",
      "type": "table",
      "schema": "main",
      "row_count": 15000
    }
  ],
  "total_count": 5
}
```

**Example Usage**:
```python
tool = DUCKDB_TOOLS['duckdb_list_tables'](config)
result = tool.execute({'include_system_tables': False})
```

---

### 2. duckdb_describe_table

**Purpose**: Get detailed schema information for a specific table

**Operation Type**: Database schema query

**Use Cases**:
- Understand table structure
- Validate data types
- Inspect sample data

**Input Parameters**:
```json
{
  "table_name": "sales_data",          // Required
  "include_sample_data": true,         // Optional
  "sample_size": 5                     // Optional
}
```

**Output**:
```json
{
  "table_name": "sales_data",
  "table_type": "table",
  "columns": [
    {
      "column_name": "id",
      "data_type": "INTEGER",
      "nullable": false,
      "is_primary_key": true
    }
  ],
  "row_count": 15000,
  "sample_data": [...]
}
```

---

### 3. duckdb_query

**Purpose**: Execute SQL queries on data files

**Operation Type**: Database SQL query execution

**Use Cases**:
- Ad-hoc data analysis
- Complex joins and aggregations
- Data transformation
- Custom reporting

**Input Parameters**:
```json
{
  "sql_query": "SELECT * FROM sales WHERE amount > 1000",
  "limit": 100,                        // Optional
  "output_format": "json"              // Optional: json, csv, table
}
```

**Output**:
```json
{
  "query": "SELECT * FROM sales...",
  "columns": ["id", "amount", "date"],
  "rows": [{...}, {...}],
  "row_count": 100,
  "execution_time_ms": 45.2,
  "limited": true
}
```

**Supported SQL Features**:
- SELECT, WHERE, JOIN (INNER, LEFT, RIGHT, FULL)
- GROUP BY, HAVING, ORDER BY
- Window functions (ROW_NUMBER, RANK, etc.)
- CTEs (WITH clauses)
- Subqueries
- Aggregate functions (SUM, AVG, COUNT, MIN, MAX)
- String functions, date functions, math functions

---

### 4. duckdb_get_stats

**Purpose**: Get statistical summary for numeric columns

**Operation Type**: Statistical analysis query

**Use Cases**:
- Data profiling
- Quality assessment
- Outlier detection
- Distribution analysis

**Input Parameters**:
```json
{
  "table_name": "sales_data",
  "columns": ["amount", "quantity"],   // Optional
  "include_percentiles": true          // Optional
}
```

**Output**:
```json
{
  "table_name": "sales_data",
  "total_rows": 15000,
  "column_statistics": {
    "amount": {
      "count": 14980,
      "null_count": 20,
      "mean": 1234.56,
      "std_dev": 456.78,
      "min": 10.00,
      "max": 9999.99,
      "percentile_25": 500.00,
      "median": 1000.00,
      "percentile_75": 1500.00,
      "unique_count": 8976,
      "data_type": "numeric"
    }
  }
}
```

---

### 5. duckdb_aggregate

**Purpose**: Perform aggregation operations with grouping

**Operation Type**: Aggregation query

**Use Cases**:
- Summary reports
- Group-by analysis
- Business metrics calculation
- Time-series aggregation

**Input Parameters**:
```json
{
  "table_name": "sales",
  "aggregations": {
    "revenue": "sum",
    "order_id": "count"
  },
  "group_by": ["region", "year"],
  "having": "sum_revenue > 10000",     // Optional
  "order_by": [
    {"column": "sum_revenue", "direction": "desc"}
  ],
  "limit": 100
}
```

**Supported Aggregation Functions**:
- `sum`: Sum of values
- `avg`: Average/mean
- `count`: Count of rows
- `min`: Minimum value
- `max`: Maximum value
- `count_distinct`: Count of unique values

**Output**:
```json
{
  "table_name": "sales",
  "aggregations_applied": {...},
  "grouped_by": ["region", "year"],
  "results": [{...}, {...}],
  "row_count": 50,
  "execution_time_ms": 23.4
}
```

---

### 6. duckdb_list_files

**Purpose**: List available data files in the data directory

**Operation Type**: File system scan

**Use Cases**:
- Discover available datasets
- Monitor data directory
- Verify file uploads
- Check data freshness

**Input Parameters**:
```json
{
  "file_type": "all",                  // all, csv, parquet, json, tsv
  "include_metadata": true
}
```

**Output**:
```json
{
  "data_directory": "/path/to/data",
  "files": [
    {
      "filename": "sales_2024.csv",
      "file_type": "csv",
      "file_path": "/path/to/data/sales_2024.csv",
      "file_size_bytes": 1048576,
      "file_size_human": "1.00 MB",
      "modified_date": "2024-01-15T10:30:00",
      "is_loaded": true,
      "table_name": "sales_2024"
    }
  ],
  "total_files": 10,
  "summary": {
    "csv_count": 5,
    "parquet_count": 3,
    "json_count": 2,
    "tsv_count": 0,
    "total_size_bytes": 52428800
  }
}
```

---

### 7. duckdb_refresh_views

**Purpose**: Refresh materialized views or reload external files

**Operation Type**: View refresh / Data reload

**Use Cases**:
- Update cached query results
- Reload changed data files
- Maintain data freshness

**Input Parameters**:
```json
{
  "view_name": "monthly_summary",      // Optional
  "reload_external_files": false
}
```

**Output**:
```json
{
  "refreshed_views": [
    {
      "view_name": "monthly_summary",
      "status": "success",
      "row_count": 1200,
      "refresh_time_ms": 156.7
    }
  ],
  "total_refreshed": 1,
  "external_files_reloaded": false
}
```

---

## API Reference

### Common Response Format

All tools return responses following this pattern:

```python
{
    "success": True/False,
    "data": {
        # Tool-specific data
    },
    "error": None or {
        "code": "ERROR_CODE",
        "message": "Error description"
    },
    "metadata": {
        "execution_time_ms": 123.45,
        "timestamp": "2024-01-15T10:30:00Z"
    }
}
```

### Error Codes

| Code | Description |
|------|-------------|
| `INVALID_INPUT` | Invalid input parameters |
| `TABLE_NOT_FOUND` | Specified table does not exist |
| `QUERY_ERROR` | SQL query execution failed |
| `FILE_NOT_FOUND` | Data file not found |
| `CONNECTION_ERROR` | Database connection failed |
| `PERMISSION_ERROR` | Insufficient permissions |

### Rate Limits

- **Default**: 60 requests per minute per tool
- **Cache TTL**: 60 seconds for repeated queries
- No authentication required

---

## Sample Code

### Example 1: Basic Data Exploration

```python
from tools.impl.duckdb_olap_tools_refactored import DUCKDB_TOOLS

# Configuration
config = {
    'data_directory': '/home/user/data/duckdb',
    'enabled': True
}

# Initialize tools
list_files = DUCKDB_TOOLS['duckdb_list_files'](config)
list_tables = DUCKDB_TOOLS['duckdb_list_tables'](config)
describe = DUCKDB_TOOLS['duckdb_describe_table'](config)

# Step 1: List available files
files_result = list_files.execute({'file_type': 'all'})
print(f"Found {files_result['total_files']} data files")

# Step 2: List loaded tables
tables_result = list_tables.execute({})
print(f"Available tables: {[t['name'] for t in tables_result['tables']]}")

# Step 3: Describe a specific table
if tables_result['tables']:
    table_name = tables_result['tables'][0]['name']
    schema = describe.execute({
        'table_name': table_name,
        'include_sample_data': True,
        'sample_size': 3
    })
    print(f"\nTable: {table_name}")
    print(f"Columns: {[c['column_name'] for c in schema['columns']]}")
    print(f"Row count: {schema['row_count']}")
```

### Example 2: Sales Analysis

```python
# Initialize query and aggregate tools
query_tool = DUCKDB_TOOLS['duckdb_query'](config)
aggregate_tool = DUCKDB_TOOLS['duckdb_aggregate'](config)

# Query: Top customers by revenue
top_customers = query_tool.execute({
    'sql_query': '''
        SELECT 
            customer_id,
            customer_name,
            SUM(order_amount) as total_revenue,
            COUNT(*) as order_count
        FROM orders
        GROUP BY customer_id, customer_name
        ORDER BY total_revenue DESC
        LIMIT 10
    ''',
    'limit': 10
})

print("Top 10 Customers:")
for row in top_customers['rows']:
    print(f"  {row['customer_name']}: ${row['total_revenue']:,.2f}")

# Aggregate: Sales by region and month
regional_sales = aggregate_tool.execute({
    'table_name': 'sales',
    'aggregations': {
        'revenue': 'sum',
        'order_id': 'count'
    },
    'group_by': ['region', 'month'],
    'order_by': [
        {'column': 'sum_revenue', 'direction': 'desc'}
    ],
    'limit': 20
})

print(f"\nRegional Sales Summary:")
print(f"Total groups: {regional_sales['row_count']}")
```

### Example 3: Data Quality Assessment

```python
# Initialize stats tool
stats_tool = DUCKDB_TOOLS['duckdb_get_stats'](config)

# Get statistics for numerical columns
stats = stats_tool.execute({
    'table_name': 'transactions',
    'columns': ['amount', 'quantity', 'discount'],
    'include_percentiles': True
})

print("Data Quality Report:")
print(f"Total rows: {stats['total_rows']}")

for col, col_stats in stats['column_statistics'].items():
    print(f"\n{col}:")
    print(f"  Non-null: {col_stats['count']} ({col_stats['null_count']} nulls)")
    print(f"  Range: [{col_stats['min']:.2f}, {col_stats['max']:.2f}]")
    print(f"  Mean: {col_stats['mean']:.2f} (±{col_stats['std_dev']:.2f})")
    print(f"  Median: {col_stats['median']:.2f}")
    print(f"  Unique values: {col_stats['unique_count']}")
```

### Example 4: Complex Join Query

```python
# Query with multiple table joins
complex_query = query_tool.execute({
    'sql_query': '''
        WITH customer_metrics AS (
            SELECT 
                c.customer_id,
                c.customer_name,
                c.region,
                COUNT(DISTINCT o.order_id) as order_count,
                SUM(o.order_amount) as total_spent,
                AVG(o.order_amount) as avg_order_value
            FROM customers c
            LEFT JOIN orders o ON c.customer_id = o.customer_id
            WHERE o.order_date >= '2024-01-01'
            GROUP BY c.customer_id, c.customer_name, c.region
        )
        SELECT 
            cm.*,
            RANK() OVER (PARTITION BY region ORDER BY total_spent DESC) as region_rank
        FROM customer_metrics cm
        WHERE order_count >= 5
        ORDER BY total_spent DESC
    ''',
    'limit': 50
})

print(f"Query executed in {complex_query['execution_time_ms']:.2f}ms")
print(f"Results: {complex_query['row_count']} rows")
```

### Example 5: Working with Different File Formats

```python
# Query CSV file directly (without loading to table)
csv_query = query_tool.execute({
    'sql_query': "SELECT * FROM read_csv_auto('/path/to/sales.csv') LIMIT 10"
})

# Query Parquet file
parquet_query = query_tool.execute({
    'sql_query': "SELECT * FROM read_parquet('/path/to/data.parquet') WHERE year = 2024"
})

# Query JSON file
json_query = query_tool.execute({
    'sql_query': '''
        SELECT 
            data->>'customer_name' as customer,
            data->>'amount' as amount
        FROM read_json_auto('/path/to/transactions.json')
    '''
})
```

---

## Schema Definitions

### Complete Input/Output Schemas

#### duckdb_list_tables

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "include_system_tables": {
      "type": "boolean",
      "description": "Include system/internal tables",
      "default": false
    }
  }
}
```

**Output Schema**:
```json
{
  "type": "object",
  "properties": {
    "tables": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {"type": "string"},
          "type": {"type": "string", "enum": ["table", "view", "external"]},
          "schema": {"type": "string"},
          "row_count": {"type": "integer"}
        }
      }
    },
    "total_count": {"type": "integer"}
  }
}
```

#### duckdb_describe_table

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "table_name": {
      "type": "string",
      "minLength": 1,
      "description": "Name of table or view"
    },
    "include_sample_data": {
      "type": "boolean",
      "default": false
    },
    "sample_size": {
      "type": "integer",
      "minimum": 1,
      "maximum": 100,
      "default": 5
    }
  },
  "required": ["table_name"]
}
```

**Output Schema**:
```json
{
  "type": "object",
  "properties": {
    "table_name": {"type": "string"},
    "table_type": {
      "type": "string",
      "enum": ["table", "view", "external"]
    },
    "columns": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "column_name": {"type": "string"},
          "data_type": {"type": "string"},
          "nullable": {"type": "boolean"},
          "default_value": {"type": ["string", "null"]},
          "is_primary_key": {"type": "boolean"}
        }
      }
    },
    "row_count": {"type": "integer"},
    "sample_data": {"type": "array"}
  }
}
```

#### duckdb_query

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "sql_query": {
      "type": "string",
      "minLength": 1,
      "description": "SQL query (read-only)"
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 10000,
      "default": 100
    },
    "output_format": {
      "type": "string",
      "enum": ["json", "csv", "table"],
      "default": "json"
    }
  },
  "required": ["sql_query"]
}
```

**Output Schema**:
```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string"},
    "columns": {
      "type": "array",
      "items": {"type": "string"}
    },
    "rows": {
      "type": "array",
      "items": {"type": "object"}
    },
    "row_count": {"type": "integer"},
    "execution_time_ms": {"type": "number"},
    "limited": {"type": "boolean"}
  }
}
```

#### duckdb_get_stats

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "table_name": {
      "type": "string",
      "minLength": 1
    },
    "columns": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Optional: specific columns"
    },
    "include_percentiles": {
      "type": "boolean",
      "default": true
    }
  },
  "required": ["table_name"]
}
```

**Output Schema**:
```json
{
  "type": "object",
  "properties": {
    "table_name": {"type": "string"},
    "total_rows": {"type": "integer"},
    "column_statistics": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "properties": {
          "count": {"type": "integer"},
          "null_count": {"type": "integer"},
          "mean": {"type": "number"},
          "std_dev": {"type": "number"},
          "min": {"type": ["number", "string"]},
          "max": {"type": ["number", "string"]},
          "percentile_25": {"type": "number"},
          "median": {"type": "number"},
          "percentile_75": {"type": "number"},
          "unique_count": {"type": "integer"},
          "data_type": {"type": "string"}
        }
      }
    }
  }
}
```

#### duckdb_aggregate

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "table_name": {
      "type": "string",
      "minLength": 1
    },
    "aggregations": {
      "type": "object",
      "additionalProperties": {
        "type": "string",
        "enum": ["sum", "avg", "count", "min", "max", "count_distinct"]
      },
      "minProperties": 1
    },
    "group_by": {
      "type": "array",
      "items": {"type": "string"}
    },
    "having": {"type": "string"},
    "order_by": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "column": {"type": "string"},
          "direction": {
            "type": "string",
            "enum": ["asc", "desc"]
          }
        }
      }
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "maximum": 10000,
      "default": 100
    }
  },
  "required": ["table_name", "aggregations"]
}
```

**Output Schema**:
```json
{
  "type": "object",
  "properties": {
    "table_name": {"type": "string"},
    "aggregations_applied": {"type": "object"},
    "grouped_by": {
      "type": "array",
      "items": {"type": "string"}
    },
    "results": {
      "type": "array",
      "items": {"type": "object"}
    },
    "row_count": {"type": "integer"},
    "execution_time_ms": {"type": "number"}
  }
}
```

#### duckdb_list_files

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "file_type": {
      "type": "string",
      "enum": ["all", "csv", "parquet", "json", "tsv"]
    },
    "include_metadata": {
      "type": "boolean",
      "default": true
    }
  }
}
```

**Output Schema**:
```json
{
  "type": "object",
  "properties": {
    "data_directory": {"type": "string"},
    "files": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "filename": {"type": "string"},
          "file_type": {"type": "string"},
          "file_path": {"type": "string"},
          "file_size_bytes": {"type": "integer"},
          "file_size_human": {"type": "string"},
          "modified_date": {"type": "string"},
          "is_loaded": {"type": "boolean"},
          "table_name": {"type": "string"}
        }
      }
    },
    "total_files": {"type": "integer"},
    "summary": {"type": "object"}
  }
}
```

#### duckdb_refresh_views

**Input Schema**:
```json
{
  "type": "object",
  "properties": {
    "view_name": {"type": "string"},
    "reload_external_files": {
      "type": "boolean",
      "default": false
    }
  }
}
```

**Output Schema**:
```json
{
  "type": "object",
  "properties": {
    "refreshed_views": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "view_name": {"type": "string"},
          "status": {
            "type": "string",
            "enum": ["success", "failed", "skipped"]
          },
          "row_count": {"type": "integer"},
          "refresh_time_ms": {"type": "number"},
          "error_message": {"type": "string"}
        }
      }
    },
    "total_refreshed": {"type": "integer"},
    "external_files_reloaded": {"type": "boolean"}
  }
}
```

---

## Limitations

### 1. File Size Limitations

- **CSV Files**: Up to 10GB (larger files may impact performance)
- **Parquet Files**: Up to 100GB (efficient columnar format)
- **JSON Files**: Up to 5GB (less efficient due to text format)
- **Memory**: Query results limited by available RAM

### 2. Query Limitations

- **Read-Only Operations**: Only SELECT queries allowed (no INSERT, UPDATE, DELETE)
- **Query Timeout**: Default 300 seconds (configurable)
- **Result Limit**: Maximum 10,000 rows per query
- **Concurrent Queries**: Limited to 10 simultaneous connections

### 3. Data Type Support

**Fully Supported**:
- INTEGER, BIGINT, SMALLINT
- DOUBLE, FLOAT, DECIMAL
- VARCHAR, TEXT
- DATE, TIMESTAMP
- BOOLEAN

**Limited Support**:
- ARRAY, STRUCT (requires specific syntax)
- JSON (requires JSON functions)
- BLOB (binary data)

**Not Supported**:
- User-defined types (UDTs)
- Spatial/Geographic types (without extension)

### 4. File Format Specific Limitations

**CSV**:
- Requires consistent column counts
- Header row recommended
- Character encoding: UTF-8 preferred
- Delimiter auto-detection (or specify explicitly)

**Parquet**:
- Schema must be consistent across files
- Compression codecs: SNAPPY, GZIP, ZSTD supported

**JSON**:
- Must be valid JSON or JSON Lines format
- Nested structures require special handling
- Less efficient than Parquet

### 5. Security Limitations

- **No Access Control**: All files in data directory are accessible
- **No Encryption**: Data stored unencrypted
- **SQL Injection**: User must validate inputs before passing to query tool
- **File System Access**: Limited to configured data directory

### 6. Performance Considerations

- **Indexes**: Limited index support (automatic for Parquet)
- **Statistics**: Automatically collected but may be stale
- **Parallel Execution**: Automatic but limited by CPU cores
- **Cache**: Query results cached for 60 seconds (configurable)

### 7. Known Issues

- **Large String Columns**: May cause memory issues with aggregations
- **Complex Joins**: Performance degrades with >5 table joins
- **Window Functions**: Can be memory-intensive on large datasets
- **Date Parsing**: May fail on non-standard date formats

---

## Troubleshooting

### Common Issues and Solutions

#### Issue 1: "Table Not Found" Error

**Symptom**: Query fails with "table does not exist"

**Solutions**:
```python
# 1. List available tables
tables = list_tables_tool.execute({})
print([t['name'] for t in tables['tables']])

# 2. Query file directly
result = query_tool.execute({
    'sql_query': "SELECT * FROM read_csv_auto('/path/to/file.csv') LIMIT 10"
})
```

#### Issue 2: Out of Memory

**Symptom**: Query fails with memory allocation error

**Solutions**:
- Reduce query result limit
- Filter data with WHERE clauses
- Use aggregations instead of raw data
- Increase available RAM
- Process data in chunks

```python
# Process in chunks
offset = 0
chunk_size = 1000

while True:
    result = query_tool.execute({
        'sql_query': f"SELECT * FROM large_table LIMIT {chunk_size} OFFSET {offset}"
    })
    
    if result['row_count'] == 0:
        break
    
    # Process chunk
    process_data(result['rows'])
    offset += chunk_size
```

#### Issue 3: Slow Query Performance

**Symptom**: Queries take longer than expected

**Solutions**:
```python
# 1. Use EXPLAIN to analyze query plan
explain_result = query_tool.execute({
    'sql_query': "EXPLAIN SELECT * FROM large_table WHERE condition"
})

# 2. Add filters early in the query
# BAD: SELECT * FROM table WHERE expensive_function(col) = value
# GOOD: SELECT * FROM table WHERE col = value

# 3. Use appropriate aggregations
aggregate_result = aggregate_tool.execute({
    'table_name': 'sales',
    'aggregations': {'amount': 'sum'},
    'group_by': ['region']
})
```

#### Issue 4: CSV Parsing Errors

**Symptom**: CSV file fails to load or parse correctly

**Solutions**:
```python
# Specify CSV parameters explicitly
result = query_tool.execute({
    'sql_query': '''
        SELECT * FROM read_csv(
            '/path/to/file.csv',
            delim=',',
            header=true,
            quote='"',
            escape='"',
            columns={
                'id': 'INTEGER',
                'name': 'VARCHAR',
                'date': 'DATE'
            }
        )
    '''
})
```

#### Issue 5: Connection Errors

**Symptom**: "Failed to connect to database"

**Solutions**:
```python
# 1. Check data directory exists
import os
data_dir = config['data_directory']
if not os.path.exists(data_dir):
    os.makedirs(data_dir, exist_ok=True)

# 2. Check permissions
if not os.access(data_dir, os.R_OK | os.W_OK):
    print("Insufficient permissions")

# 3. Close and reinitialize connection
tool.close()
tool = DUCKDB_TOOLS['duckdb_query'](config)
```

#### Issue 6: Date/Time Parsing Issues

**Symptom**: Date columns parsed as strings

**Solutions**:
```python
# Explicit date conversion
result = query_tool.execute({
    'sql_query': '''
        SELECT 
            STRPTIME(date_string, '%Y-%m-%d') as date_column,
            *
        FROM my_table
        WHERE STRPTIME(date_string, '%Y-%m-%d') >= '2024-01-01'
    '''
})
```

### Debugging Tips

1. **Enable Verbose Logging**:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

2. **Test Queries Incrementally**:
```python
# Start simple
query_tool.execute({'sql_query': 'SELECT COUNT(*) FROM table'})
# Add complexity gradually
query_tool.execute({'sql_query': 'SELECT * FROM table LIMIT 1'})
```

3. **Validate Input Data**:
```python
# Check file integrity
files = list_files_tool.execute({'file_type': 'all'})
for f in files['files']:
    print(f"{f['filename']}: {f['file_size_human']}")
```

4. **Monitor Performance**:
```python
# Track execution time
import time
start = time.time()
result = query_tool.execute({'sql_query': '...'})
print(f"Query took {time.time() - start:.2f}s")
print(f"DuckDB reported: {result.get('execution_time_ms', 0)}ms")
```

---

## Appendix

### A. DuckDB SQL Functions Reference

#### Aggregate Functions
- `SUM()`, `AVG()`, `COUNT()`, `MIN()`, `MAX()`
- `STDDEV()`, `VARIANCE()`
- `STRING_AGG()`, `ARRAY_AGG()`
- `PERCENTILE_CONT()`, `PERCENTILE_DISC()`

#### String Functions
- `CONCAT()`, `SUBSTRING()`, `UPPER()`, `LOWER()`
- `TRIM()`, `LTRIM()`, `RTRIM()`
- `REPLACE()`, `SPLIT_PART()`
- `REGEXP_MATCHES()`, `REGEXP_REPLACE()`

#### Date/Time Functions
- `CURRENT_DATE`, `CURRENT_TIMESTAMP`
- `DATE_TRUNC()`, `DATE_PART()`
- `DATEADD()`, `DATEDIFF()`
- `STRPTIME()`, `STRFTIME()`

#### Window Functions
- `ROW_NUMBER()`, `RANK()`, `DENSE_RANK()`
- `LAG()`, `LEAD()`
- `FIRST_VALUE()`, `LAST_VALUE()`
- `NTILE()`, `PERCENT_RANK()`

### B. Performance Tuning Guidelines

1. **Use Parquet for Large Datasets**: 10-100x faster than CSV
2. **Limit Result Sets**: Always use LIMIT for exploratory queries
3. **Filter Early**: Apply WHERE clauses before aggregations
4. **Use Appropriate Data Types**: INTEGER vs BIGINT, VARCHAR vs TEXT
5. **Avoid SELECT ***: Specify only needed columns
6. **Use CTEs**: Break complex queries into readable parts
7. **Monitor Memory**: Large aggregations can exhaust memory

### C. File Format Recommendations

| Use Case | Recommended Format | Reason |
|----------|-------------------|---------|
| Large datasets (>1GB) | Parquet | Columnar, compressed |
| Wide tables (>100 cols) | Parquet | Efficient column access |
| Nested data | Parquet or JSON | Native structure support |
| Human-readable | CSV | Easy to inspect/edit |
| Streaming data | JSON Lines | Append-friendly |
| Archive/compliance | Parquet | Efficient long-term storage |

---

## Support & Contact

**Copyright © 2025-2030 Ashutosh Sinha. All rights reserved.**

**Author**: Ashutosh Sinha  
**Email**: ajsinha@gmail.com  
**Version**: 1.0.0  
**Last Updated**: October 31, 2025

---

## License

This software is proprietary and confidential. Unauthorized copying, distribution, or use is strictly prohibited.

---

**End of Reference Guide**
