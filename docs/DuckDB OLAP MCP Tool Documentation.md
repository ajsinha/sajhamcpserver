# DuckDB OLAP MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The DuckDB OLAP MCP Tool provides analytical database capabilities with OLAP operations, data aggregation, and advanced SQL analytics using DuckDB. **Enhanced with automatic file discovery, intelligent table management, auto-refresh capabilities, and parameterized queries with automatic IN clause generation.**

## Key Features

### Automatic File Discovery
- **Auto-detects CSV and Parquet files** in the data folder upon instantiation
- **Recursive scanning** - discovers files in subdirectories
- **Smart table naming** - converts filenames to lowercase table names (e.g., `Sales_Data.csv` → `sales_data`)
- **Schema inference** - automatically detects column types and structure

### Intelligent Table Management
- **Automatic table creation** from discovered files
- **Change detection** - monitors file modifications (size and timestamp)
- **Auto-refresh** - periodically checks for new, modified, or deleted files
- **Synchronized operations** - thread-safe table updates

### Dynamic Refresh System
- **Configurable refresh interval** (default: 10 minutes)
- **Background refresh thread** for continuous monitoring
- **Manual refresh trigger** available via API
- **Change tracking** - reports new, updated, and deleted files

### Parameterized Queries (NEW!)
- **Multiple placeholder styles** - `:name`, `$name`, `{name}`
- **Automatic IN clause generation** - list arguments become IN clauses
- **SQL injection protection** - proper escaping and quoting
- **Type-aware formatting** - handles strings, numbers, dates, booleans, nulls

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DUCKDB_DATA_FOLDER` | Path to data folder containing CSV/Parquet files | `data` |
| `DUCKDB_REFRESH_INTERVAL` | Auto-refresh interval in minutes | `10` |
| `DUCKDB_AUTO_REFRESH` | Enable automatic table refresh (true/false) | `true` |

### Example Configuration
```bash
export DUCKDB_DATA_FOLDER=/path/to/data
export DUCKDB_REFRESH_INTERVAL=5
export DUCKDB_AUTO_REFRESH=true
```

## Parameterized Queries

### Overview
Parameterized queries allow you to write SQL with placeholders that are safely replaced with values at execution time. This feature provides:
- **Security**: Prevents SQL injection attacks
- **Convenience**: Automatic IN clause generation for lists
- **Flexibility**: Multiple placeholder syntaxes supported
- **Type safety**: Proper handling of different data types

### Placeholder Styles

The tool supports three placeholder styles that can be used interchangeably:

| Style | Example | Description |
|-------|---------|-------------|
| Colon | `:region` | Most common in SQL databases |
| Dollar | `$region` | PostgreSQL-style |
| Braces | `{region}` | Python format-style |

### Automatic IN Clause Generation

**The killer feature**: When you pass a list or tuple as a parameter value, it automatically generates an IN clause!

**Before (manual):**
```python
regions = ['North', 'South', 'East']
query = f"SELECT * FROM sales WHERE region IN ('{regions[0]}', '{regions[1]}', '{regions[2]}')"
```

**After (automatic):**
```python
query = "SELECT * FROM sales WHERE region IN :regions"
arguments = {"regions": ['North', 'South', 'East']}
# Automatically becomes: WHERE region IN ('North', 'South', 'East')
```

### Type Handling

The parameterization engine properly formats different data types:

| Python Type | SQL Output | Example |
|-------------|------------|---------|
| `None` | `NULL` | `None` → `NULL` |
| `bool` | `TRUE/FALSE` | `True` → `TRUE` |
| `int/float` | Raw number | `42` → `42` |
| `str` | Quoted, escaped | `"O'Brien"` → `'O''Brien'` |
| `datetime/date` | ISO format | `date(2024,1,15)` → `'2024-01-15'` |
| `list/tuple` | IN clause | `[1,2,3]` → `(1, 2, 3)` |

### Usage Examples

#### Example 1: Simple Parameter Replacement
```python
# Using colon style
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': 'SELECT * FROM sales_data WHERE region = :region',
    'arguments': {'region': 'North'}
})

# Using dollar style
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': 'SELECT * FROM sales_data WHERE region = $region',
    'arguments': {'region': 'North'}
})

# Using brace style
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': 'SELECT * FROM sales_data WHERE region = {region}',
    'arguments': {'region': 'North'}
})
```

#### Example 2: List Arguments (IN Clause)
```python
# Automatically generates IN clause
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': '''
        SELECT product, SUM(total_amount) as revenue
        FROM sales_data
        WHERE region IN :regions
        AND product IN :products
        GROUP BY product
    ''',
    'arguments': {
        'regions': ['North', 'South', 'East'],
        'products': ['Laptop', 'Phone', 'Tablet']
    }
})

# Processed query becomes:
# SELECT product, SUM(total_amount) as revenue
# FROM sales_data
# WHERE region IN ('North', 'South', 'East')
# AND product IN ('Laptop', 'Phone', 'Tablet')
# GROUP BY product
```

#### Example 3: Mixed Parameter Types
```python
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': '''
        SELECT *
        FROM sales_data
        WHERE date >= :start_date
        AND date <= :end_date
        AND region IN :regions
        AND quantity > :min_quantity
        AND status = :status
    ''',
    'arguments': {
        'start_date': date(2024, 1, 1),
        'end_date': date(2024, 12, 31),
        'regions': ['North', 'South'],
        'min_quantity': 5,
        'status': 'Active'
    }
})
```

#### Example 4: Numeric Lists
```python
# Works with numeric lists too
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': '''
        SELECT *
        FROM sales_data
        WHERE quantity IN :quantities
        AND unit_price > :min_price
    ''',
    'arguments': {
        'quantities': [1, 5, 10],
        'min_price': 100.00
    }
})
```

#### Example 5: Empty Lists
```python
# Empty lists are handled safely
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': 'SELECT * FROM sales_data WHERE region IN :regions',
    'arguments': {'regions': []}
})
# Becomes: WHERE region IN (NULL) - safe and returns no results
```

#### Example 6: Complex Analytics Query
```python
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': '''
        WITH filtered_sales AS (
            SELECT *
            FROM sales_data
            WHERE region IN :regions
            AND date BETWEEN :start_date AND :end_date
        )
        SELECT 
            product,
            COUNT(*) as order_count,
            SUM(total_amount) as total_revenue,
            AVG(total_amount) as avg_order_value
        FROM filtered_sales
        WHERE product IN :products
        GROUP BY product
        HAVING COUNT(*) > :min_orders
        ORDER BY total_revenue DESC
    ''',
    'arguments': {
        'regions': ['North', 'East', 'West'],
        'start_date': '2024-01-01',
        'end_date': '2024-12-31',
        'products': ['Laptop', 'Phone', 'Monitor'],
        'min_orders': 10
    }
})
```

### Response Format

Parameterized queries return enhanced results:

```json
{
  "original_query": "SELECT * FROM sales WHERE region IN :regions",
  "processed_query": "SELECT * FROM sales WHERE region IN ('North', 'South')",
  "results": [...],
  "row_count": 450,
  "columns": ["order_id", "date", "product", ...],
  "parameter_metadata": {
    "placeholders_replaced": 1,
    "in_clauses_generated": 1,
    "original_params": {"regions": ["North", "South"]}
  }
}
```

### Security Benefits

The parameterization system provides protection against SQL injection:

**Unsafe (DON'T DO THIS):**
```python
user_input = "North'; DROP TABLE sales_data; --"
query = f"SELECT * FROM sales WHERE region = '{user_input}'"
# DANGEROUS! Could delete your table
```

**Safe (DO THIS):**
```python
user_input = "North'; DROP TABLE sales_data; --"
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': 'SELECT * FROM sales WHERE region = :region',
    'arguments': {'region': user_input}
})
# SAFE! Treats input as literal string: 'North''; DROP TABLE sales_data; --'
```

### Backward Compatibility

The `execute_query` method now accepts an optional `arguments` parameter:

```python
# Old way (still works)
result = duckdb_tool.handle_tool_call('execute_query', {
    'query': "SELECT * FROM sales WHERE region = 'North'"
})

# New way with arguments
result = duckdb_tool.handle_tool_call('execute_query', {
    'query': 'SELECT * FROM sales WHERE region = :region',
    'arguments': {'region': 'North'}
})
```

## How It Works

### Initialization Process
1. **Scan data folder** for `.csv` and `.parquet` files
2. **Generate table names** from filenames (lowercase, sanitized)
3. **Create tables** with auto-detected schemas
4. **Track file metadata** (modification time, size)
5. **Create default views** (sales_summary, customer_sales if applicable)
6. **Start background refresh** (if auto-refresh enabled)

### Refresh Cycle
Every N minutes (configurable), the system:
1. **Scans for new files** → Creates new tables
2. **Checks for modifications** → Refreshes changed tables
3. **Detects deletions** → Removes corresponding tables
4. **Updates metadata** → Records changes and timestamps

### Table Naming Convention
Files are converted to table names using these rules:
- Convert to lowercase
- Replace spaces and hyphens with underscores
- Remove special characters
- Keep only alphanumeric and underscores

**Examples:**
- `Sales Data.csv` → `sales_data`
- `Customer-Info.parquet` → `customer_info`
- `Q4_Report_2024.csv` → `q4_report_2024`

## Sample Data

### Sales Data Table (`sales_data.csv`)
- 1000 sample records
- Products: Laptop, Phone, Tablet, Monitor, Keyboard
- Regions: North, South, East, West, Central
- Fields: order_id, date, product, region, quantity, unit_price, customer_id, discount, total_amount

### Customer Data Table (`customer_data.csv`)
- 200 sample customers
- Countries: USA, Canada, UK, Germany, France, Japan
- Segments: Enterprise, SMB, Consumer, Government
- Fields: customer_id, company_name, country, segment, registration_date, credit_limit, status

### Pre-built Views
- `sales_summary`: Aggregated sales by date, product, region
- `customer_sales`: Customer purchase analytics

## Available Methods

### New/Enhanced Methods

#### 1. execute_query (ENHANCED)
Execute a DuckDB SQL query with optional parameterization.

**Parameters:**
- `query`: SQL query string (required)
- `arguments`: Optional dictionary of parameter values

**Returns:**
- Query results (limited to 100 rows)
- Row count
- Column names
- Parameter metadata (if arguments provided)

**Example:**
```python
result = duckdb_tool.handle_tool_call('execute_query', {
    'query': 'SELECT * FROM sales_data WHERE region IN :regions',
    'arguments': {'regions': ['North', 'South']}
})
```

#### 2. execute_parameterized_query (NEW)
Execute a parameterized query with automatic IN clause generation.

**Parameters:**
- `query`: SQL query with placeholders (required)
- `arguments`: Dictionary of parameter values (required)

**Returns:**
- Original and processed queries
- Results
- Parameter metadata

**Example:**
```python
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': '''
        SELECT product, SUM(total_amount) as revenue
        FROM sales_data
        WHERE region IN :regions AND date >= :start_date
        GROUP BY product
    ''',
    'arguments': {
        'regions': ['North', 'East'],
        'start_date': '2024-01-01'
    }
})
```

#### 3. get_loaded_files
Get information about currently loaded files and refresh status.

**Parameters:** None

**Returns:**
- List of loaded files with metadata
- Table names and row counts
- Refresh interval and auto-refresh status
- File sizes and load timestamps

#### 4. refresh_tables
Manually trigger table refresh to discover new, modified, or deleted files.

**Parameters:** None

**Returns:**
- Changes detected (new, updated, deleted files)
- Total tables count
- Success confirmation

### Core Methods

#### 5. list_tables
List all tables and views in DuckDB **with source file information**.

**Returns:**
- Table names and types
- Row counts
- **Source file paths** (for auto-discovered tables)

#### 6. get_table_schema
Get schema information for a table.

**Parameters:**
- `table_name`: Name of table (required)

**Returns:**
- Column details (name, type, nullable, default)
- Sample data (5 rows)

#### 7. aggregate_data
Perform aggregation operations.

**Parameters:**
- `table` (default: 'sales_data'): Table to aggregate
- `group_by`: List of grouping columns (required)
- `aggregations`: Dictionary of column: function pairs
- `filters` (optional): Filter conditions

#### 8. pivot_data
Create pivot table.

#### 9. time_series_analysis
Perform time series analysis.

#### 10. top_n_analysis
Get top N records by a metric.

#### 11. window_functions
Apply window functions for advanced analytics.

#### 12. join_tables
Join multiple tables.

#### 13. load_csv
Load a new CSV/Parquet file into DuckDB.

#### 14. export_results
Export query results to CSV.

#### 15. create_materialized_view
Create a materialized view for performance.

#### 16. analyze_performance
Analyze query performance.

## Usage Examples

### Parameterized Query Workflow

```python
# 1. Basic parameterized query
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': 'SELECT * FROM sales_data WHERE product = :product',
    'arguments': {'product': 'Laptop'}
})

# 2. Multi-region analysis with IN clause
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': '''
        SELECT region, COUNT(*) as orders, SUM(total_amount) as revenue
        FROM sales_data
        WHERE region IN :regions
        GROUP BY region
    ''',
    'arguments': {'regions': ['North', 'South', 'East']}
})

# 3. Date range with multiple filters
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': '''
        SELECT *
        FROM sales_data
        WHERE date BETWEEN :start_date AND :end_date
        AND product IN :products
        AND quantity >= :min_qty
    ''',
    'arguments': {
        'start_date': '2024-01-01',
        'end_date': '2024-12-31',
        'products': ['Laptop', 'Phone'],
        'min_qty': 5
    }
})
```

### Auto-Discovery Workflow

```python
# 1. Drop CSV/Parquet files in data folder
# /data/sales_2024.csv
# /data/products.parquet
# /data/regions.csv

# 2. Tool automatically discovers and loads on initialization
# Tables created: sales_2024, products, regions

# 3. Check loaded files
result = duckdb_tool.handle_tool_call('get_loaded_files', {})

# 4. Query with parameters
result = duckdb_tool.handle_tool_call('execute_parameterized_query', {
    'query': 'SELECT * FROM sales_2024 WHERE region IN :regions',
    'arguments': {'regions': ['North', 'South']}
})
```

### Dynamic Dashboard Example

```python
# Build a dynamic sales dashboard
def get_sales_dashboard(regions, products, date_range):
    return duckdb_tool.handle_tool_call('execute_parameterized_query', {
        'query': '''
            SELECT 
                region,
                product,
                DATE_TRUNC('month', date) as month,
                SUM(total_amount) as revenue,
                COUNT(*) as orders,
                AVG(total_amount) as avg_order
            FROM sales_data
            WHERE region IN :regions
            AND product IN :products
            AND date BETWEEN :start_date AND :end_date
            GROUP BY region, product, month
            ORDER BY month, region, product
        ''',
        'arguments': {
            'regions': regions,
            'products': products,
            'start_date': date_range[0],
            'end_date': date_range[1]
        }
    })

# Use it
dashboard = get_sales_dashboard(
    regions=['North', 'East'],
    products=['Laptop', 'Phone', 'Tablet'],
    date_range=('2024-01-01', '2024-06-30')
)
```

## Best Practices

### Parameterized Queries
1. **Always use parameters for user input** - prevents SQL injection
2. **Use lists for multi-value filters** - automatic IN clause generation
3. **Choose consistent placeholder style** - stick with one style per project
4. **Handle empty lists** - the tool safely converts them to `(NULL)`
5. **Combine with CTEs** - create complex, safe queries

### File Management
1. **File Naming**: Use descriptive, lowercase names with underscores
2. **Refresh Interval**: Set based on data update frequency (default 10 min is good for most cases)
3. **File Size**: DuckDB handles large files efficiently, but consider partitioning very large datasets
4. **Schema Stability**: Avoid changing column names/types in existing files
5. **Manual Refresh**: Use when you need immediate updates before auto-refresh cycle

## Performance Considerations

### Parameterized Queries
- **Zero overhead**: Parameter substitution happens before query execution
- **Query plan caching**: DuckDB can cache execution plans for similar queries
- **Large lists**: IN clauses with 1000+ items may impact performance; consider alternatives

### Auto-Discovery
- **Lazy loading**: Files only loaded into memory when queried
- **Incremental updates**: Only changed files are refreshed
- **Parallel processing**: DuckDB uses multiple cores automatically

## Troubleshooting

### Parameterized Query Issues

**Problem**: Placeholder not being replaced
```python
# Check: Make sure placeholder name matches argument key
query = "SELECT * FROM sales WHERE region = :region_name"
arguments = {"region": "North"}  # ❌ Wrong key!
arguments = {"region_name": "North"}  # ✅ Correct
```

**Problem**: IN clause not working with single value
```python
# Solution: Always use list for IN clause
arguments = {"regions": "North"}  # ❌ Single string
arguments = {"regions": ["North"]}  # ✅ List with one item
```

**Problem**: Special characters in string values
```python
# Solution: The tool handles escaping automatically
arguments = {"name": "O'Brien"}  # ✅ Automatically becomes 'O''Brien'
```

## Migration Guide

### From Previous Version
The enhanced version is **fully backward compatible**. Existing code continues to work without changes.

**What's New:**
- Parameterized queries with `:name`, `$name`, `{name}` placeholders
- Automatic IN clause generation for list arguments
- Enhanced `execute_query` accepts optional `arguments` parameter
- New `execute_parameterized_query` method for explicit parameterization
- All previous features still work unchanged

**No Breaking Changes:**
- All existing methods work as before
- Simple queries still work without parameters
- File discovery and refresh unchanged

## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.