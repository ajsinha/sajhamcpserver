# SQL Select Search MCP Tool Reference Guide

**Copyright All rights reserved 2025-2030, Ashutosh Sinha**  
**Email: ajsinha@gmail.com**  
**Version: 2.2.0**  
**Last Updated: October 31, 2025**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [System Requirements](#system-requirements)
4. [Authentication & Security](#authentication--security)
5. [Data Sources Configuration](#data-sources-configuration)
6. [Tool Details](#tool-details)
7. [API Reference](#api-reference)
8. [Usage Examples](#usage-examples)
9. [Schema Specifications](#schema-specifications)
10. [Limitations](#limitations)
11. [Troubleshooting](#troubleshooting)
12. [Architecture Diagrams](#architecture-diagrams)

---

## Overview

The SQL Select Search MCP Tool is a comprehensive data querying solution that provides safe, read-only SQL access to local data sources. Built on DuckDB, it offers six specialized tools for data exploration, analysis, and querying without requiring database installation or configuration.

### Key Features

- **Zero Configuration Database**: Uses DuckDB in-memory engine
- **Multi-Format Support**: CSV, Parquet, and JSON file formats
- **Safety First**: Read-only operations with query validation
- **No External Dependencies**: All operations are local
- **MCP Compatible**: Fully compliant with Model Context Protocol
- **Comprehensive Toolset**: Six specialized tools for different query patterns

### How It Works

The tool operates through **direct database queries on local files** using DuckDB:

1. **Data Loading**: Files from the configured data directory are loaded into DuckDB views
2. **Query Processing**: SQL queries are executed against these in-memory views
3. **Result Formatting**: Query results are returned in structured JSON format
4. **No Network Operations**: All processing is local - no web scraping, crawling, or external API calls

```
┌─────────────────┐
│  Local CSV/     │
│  Parquet/JSON   │
│  Files          │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   DuckDB        │
│   In-Memory     │
│   Engine        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  SQL Query      │
│  Processing     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  JSON Response  │
└─────────────────┘
```

---

## Architecture

### Component Overview

```
┌──────────────────────────────────────────────────────────┐
│                    SQL Select MCP Tool                    │
├──────────────────────────────────────────────────────────┤
│                                                           │
│  ┌────────────────────────────────────────────────────┐  │
│  │         SqlSelectBaseTool (Base Class)            │  │
│  │  - DuckDB Connection Management                   │  │
│  │  - Data Source Registration                       │  │
│  │  - Shared Utilities                               │  │
│  └───────────────────┬────────────────────────────────┘  │
│                      │                                    │
│       ┌──────────────┼──────────────┐                    │
│       │              │              │                    │
│  ┌────▼────┐   ┌────▼────┐   ┌────▼────┐                │
│  │ List    │   │Describe │   │ Execute │                │
│  │ Sources │   │ Source  │   │  Query  │                │
│  └─────────┘   └─────────┘   └─────────┘                │
│                                                           │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐                │
│  │ Sample  │   │   Get   │   │  Count  │                │
│  │  Data   │   │ Schema  │   │  Rows   │                │
│  └─────────┘   └─────────┘   └─────────┘                │
│                                                           │
└──────────────────────────────────────────────────────────┘
```

### Class Hierarchy

```python
BaseMCPTool (Abstract Base)
    │
    └── SqlSelectBaseTool
            │
            ├── SqlSelectListSourcesTool
            ├── SqlSelectDescribeSourceTool
            ├── SqlSelectExecuteQueryTool
            ├── SqlSelectSampleDataTool
            ├── SqlSelectGetSchemaTool
            └── SqlSelectCountRowsTool
```

### Core Components

#### 1. SqlSelectBaseTool (Base Class)

**Responsibilities:**
- Initialize and manage DuckDB connections
- Register data sources as views
- Provide shared utility methods
- Handle error responses
- Manage connection lifecycle

**Key Methods:**
```python
__init__(config: Dict) -> None
_initialize_connection() -> None
_register_data_sources() -> None
_error_response(error_message: str) -> Dict
__del__() -> None
```

#### 2. DuckDB Integration

**Connection Type:** In-memory (`:memory:`)

**Supported File Formats:**
- CSV: `read_csv_auto()`
- Parquet: `read_parquet()`
- JSON: `read_json_auto()`

**View Creation:**
```sql
CREATE OR REPLACE VIEW {source_name} AS 
SELECT * FROM read_csv_auto('{file_path}')
```

---

## System Requirements

### Dependencies

```python
# Core Dependencies
import os
import duckdb
from typing import Dict, Any, List, Optional
from datetime import datetime
from tools.base_mcp_tool import BaseMCPTool
```

### Python Version
- Python 3.8 or higher

### Required Packages
```bash
pip install duckdb
```

### File System Requirements
- Read access to data directory
- Minimum 100MB free memory for DuckDB operations
- File formats: `.csv`, `.parquet`, `.json`

---

## Authentication & Security

### Authentication Requirements

**No authentication required.** The tool operates on local files only.

### API Keys

**No API keys needed.** All operations are local and do not require external service credentials.

### Security Features

1. **Read-Only Operations**
   - Only SELECT queries are allowed
   - Forbidden keywords: DROP, DELETE, UPDATE, INSERT, CREATE, ALTER, TRUNCATE

2. **Query Validation**
   ```python
   # Validation checks
   - Must start with SELECT
   - No dangerous keywords
   - Automatic LIMIT enforcement (max 10,000 rows)
   ```

3. **File Access Control**
   - Restricted to configured data directory
   - No file system traversal
   - Only registered data sources are accessible

4. **Error Handling**
   - Sanitized error messages
   - No sensitive information leakage
   - Comprehensive logging

---

## Data Sources Configuration

### Configuration Structure

```json
{
  "data_directory": "data/sqlselect",
  "data_sources": {
    "source_name": {
      "file": "filename.csv",
      "type": "csv",
      "description": "Source description"
    }
  }
}
```

### Example Configuration

```json
{
  "data_directory": "data/sqlselect",
  "data_sources": {
    "customers": {
      "file": "customers.csv",
      "type": "csv",
      "description": "Customer master data"
    },
    "orders": {
      "file": "orders.csv",
      "type": "csv",
      "description": "Order transactions"
    },
    "products": {
      "file": "products.csv",
      "type": "csv",
      "description": "Product catalog"
    },
    "sales": {
      "file": "sales.csv",
      "type": "csv",
      "description": "Sales data with customer and product details"
    }
  }
}
```

### Supported File Types

| Type | Extension | DuckDB Function |
|------|-----------|----------------|
| CSV | .csv | `read_csv_auto()` |
| Parquet | .parquet | `read_parquet()` |
| JSON | .json | `read_json_auto()` |

---

## Tool Details

### 1. sqlselect_list_sources

**Purpose:** List all available data sources with metadata

**Input Schema:**
```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

**Output Schema:**
```json
{
  "success": true,
  "sources": [
    {
      "name": "customers",
      "file": "customers.csv",
      "type": "csv",
      "description": "Customer master data"
    }
  ],
  "count": 4,
  "timestamp": "2025-10-31T12:00:00"
}
```

**Use Cases:**
- Data source discovery
- Database catalog exploration
- Available tables listing
- Data inventory management

---

### 2. sqlselect_describe_source

**Purpose:** Get detailed information about a specific data source

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "source_name": {
      "type": "string",
      "description": "Name of the data source to describe"
    }
  },
  "required": ["source_name"]
}
```

**Output Schema:**
```json
{
  "success": true,
  "source_name": "customers",
  "file": "customers.csv",
  "type": "csv",
  "description": "Customer master data",
  "row_count": 1000,
  "columns": [
    {
      "column_name": "customer_id",
      "data_type": "INTEGER",
      "nullable": "NO",
      "key": "PRI"
    }
  ],
  "timestamp": "2025-10-31T12:00:00"
}
```

**Use Cases:**
- Understanding data structure
- Schema validation
- Data profiling
- Documentation generation
- Query planning

---

### 3. sqlselect_execute_query

**Purpose:** Execute SQL SELECT queries with safety checks

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "SQL SELECT query to execute"
    },
    "limit": {
      "type": "integer",
      "description": "Maximum rows to return",
      "default": 100,
      "minimum": 1,
      "maximum": 10000
    }
  },
  "required": ["query"]
}
```

**Output Schema:**
```json
{
  "success": true,
  "columns": ["customer_id", "customer_name"],
  "rows": [
    {"customer_id": 1, "customer_name": "John Doe"},
    {"customer_id": 2, "customer_name": "Jane Smith"}
  ],
  "row_count": 2,
  "query": "SELECT * FROM customers LIMIT 100",
  "timestamp": "2025-10-31T12:00:00"
}
```

**Safety Features:**
- Only SELECT queries allowed
- Forbidden keywords validation
- Automatic LIMIT enforcement
- Query result size limiting

**Use Cases:**
- Ad-hoc data analysis
- Business intelligence queries
- Data exploration
- Report generation
- Complex analytics

---

### 4. sqlselect_sample_data

**Purpose:** Retrieve sample rows for quick preview

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "source_name": {
      "type": "string",
      "description": "Name of the data source"
    },
    "limit": {
      "type": "integer",
      "description": "Number of sample rows",
      "default": 10,
      "minimum": 1,
      "maximum": 1000
    }
  },
  "required": ["source_name"]
}
```

**Output Schema:**
```json
{
  "success": true,
  "source_name": "customers",
  "columns": ["customer_id", "customer_name", "email"],
  "rows": [
    {"customer_id": 1, "customer_name": "John", "email": "john@example.com"}
  ],
  "row_count": 10,
  "timestamp": "2025-10-31T12:00:00"
}
```

**Use Cases:**
- Data preview
- Quick data inspection
- Understanding data format
- Data quality checks
- Example data for documentation

---

### 5. sqlselect_get_schema

**Purpose:** Get detailed schema information

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "source_name": {
      "type": "string",
      "description": "Name of the data source"
    }
  },
  "required": ["source_name"]
}
```

**Output Schema:**
```json
{
  "success": true,
  "source_name": "customers",
  "schema": [
    {
      "column_name": "customer_id",
      "data_type": "INTEGER",
      "nullable": "NO",
      "key": null
    }
  ],
  "column_count": 5,
  "timestamp": "2025-10-31T12:00:00"
}
```

**Use Cases:**
- Schema discovery
- Data modeling
- Query building assistance
- Data type validation
- Documentation generation
- ETL pipeline design

---

### 6. sqlselect_count_rows

**Purpose:** Count rows with optional filtering

**Input Schema:**
```json
{
  "type": "object",
  "properties": {
    "source_name": {
      "type": "string",
      "description": "Name of the data source"
    },
    "where_clause": {
      "type": "string",
      "description": "Optional WHERE clause (without 'WHERE' keyword)"
    }
  },
  "required": ["source_name"]
}
```

**Output Schema:**
```json
{
  "success": true,
  "source_name": "customers",
  "row_count": 1500,
  "where_clause": "status = 'active'",
  "timestamp": "2025-10-31T12:00:00"
}
```

**Use Cases:**
- Data volume assessment
- Data quality validation
- Filter effectiveness testing
- Segment size analysis
- Data profiling
- Reporting metrics
- ETL validation

---

## API Reference

### Base Class Methods

#### initialize_connection()
```python
def _initialize_connection(self) -> None:
    """Initialize DuckDB connection and load data sources"""
```

#### register_data_sources()
```python
def _register_data_sources(self) -> None:
    """Register all configured data sources as DuckDB tables/views"""
```

#### error_response()
```python
def _error_response(self, error_message: str) -> Dict[str, Any]:
    """Generate standardized error response"""
```

### Tool Instantiation

```python
from tools.impl.sqlselect_tool_refactored import SQLSELECT_TOOLS

# Get tool class
ToolClass = SQLSELECT_TOOLS['sqlselect_list_sources']

# Create instance with config
tool = ToolClass(config={
    'data_directory': 'data/sqlselect',
    'data_sources': {
        'customers': {
            'file': 'customers.csv',
            'type': 'csv',
            'description': 'Customer data'
        }
    }
})

# Execute tool
result = tool.execute({})
```

---

## Usage Examples

### Example 1: List All Data Sources

```python
from sqlselect_tool_refactored import SqlSelectListSourcesTool

# Initialize tool
tool = SqlSelectListSourcesTool(config)

# Execute
result = tool.execute({})

# Result
{
    'success': True,
    'sources': [
        {'name': 'customers', 'file': 'customers.csv', 'type': 'csv'},
        {'name': 'orders', 'file': 'orders.csv', 'type': 'csv'}
    ],
    'count': 2
}
```

### Example 2: Describe a Data Source

```python
from sqlselect_tool_refactored import SqlSelectDescribeSourceTool

tool = SqlSelectDescribeSourceTool(config)

result = tool.execute({'source_name': 'customers'})

# Returns: schema, row count, column details
```

### Example 3: Execute Complex Query

```python
from sqlselect_tool_refactored import SqlSelectExecuteQueryTool

tool = SqlSelectExecuteQueryTool(config)

result = tool.execute({
    'query': '''
        SELECT 
            c.customer_name,
            COUNT(o.order_id) as order_count,
            SUM(o.total_amount) as total_spent
        FROM customers c
        LEFT JOIN orders o ON c.customer_id = o.customer_id
        GROUP BY c.customer_name
        ORDER BY total_spent DESC
    ''',
    'limit': 50
})
```

### Example 4: Sample Data Preview

```python
from sqlselect_tool_refactored import SqlSelectSampleDataTool

tool = SqlSelectSampleDataTool(config)

result = tool.execute({
    'source_name': 'products',
    'limit': 5
})

# Returns: First 5 rows from products
```

### Example 5: Count with Filtering

```python
from sqlselect_tool_refactored import SqlSelectCountRowsTool

tool = SqlSelectCountRowsTool(config)

result = tool.execute({
    'source_name': 'orders',
    'where_clause': "order_date >= '2024-01-01' AND status = 'completed'"
})

# Returns: Count of matching orders
```

### Example 6: Get Schema Details

```python
from sqlselect_tool_refactored import SqlSelectGetSchemaTool

tool = SqlSelectGetSchemaTool(config)

result = tool.execute({'source_name': 'sales'})

# Returns: Complete schema with data types
```

---

## Schema Specifications

### Input/Output Standards

All tools follow consistent schema patterns:

**Success Response:**
```json
{
  "success": true,
  "timestamp": "2025-10-31T12:00:00.000Z",
  "...": "tool-specific fields"
}
```

**Error Response:**
```json
{
  "success": false,
  "error": "Error message description",
  "timestamp": "2025-10-31T12:00:00.000Z"
}
```

### Data Type Mappings

| CSV Type | DuckDB Type | JSON Type |
|----------|-------------|-----------|
| Integer | INTEGER | number |
| Float | DOUBLE | number |
| String | VARCHAR | string |
| Date | DATE | string (ISO) |
| Boolean | BOOLEAN | boolean |
| Timestamp | TIMESTAMP | string (ISO) |

---

## Limitations

### Query Limitations

1. **Read-Only Operations**
   - Only SELECT statements allowed
   - No data modification operations
   - No schema changes permitted

2. **Result Size Limits**
   - Default limit: 100 rows
   - Maximum limit: 10,000 rows per query
   - Sample data: 1,000 rows maximum

3. **Query Complexity**
   - No stored procedures
   - No user-defined functions
   - Standard SQL operations only

### Data Source Limitations

1. **File Size**
   - Depends on available memory
   - Large files may cause performance issues
   - Recommended: < 1GB per file

2. **File Formats**
   - CSV, Parquet, JSON only
   - No binary formats
   - No database dump files

3. **Data Volume**
   - In-memory processing
   - Limited by system RAM
   - Consider data sampling for large datasets

### Technical Limitations

1. **Concurrency**
   - Single connection per tool instance
   - No connection pooling
   - Thread-safety not guaranteed

2. **Performance**
   - First query may be slower (data loading)
   - Subsequent queries benefit from caching
   - Large joins may be memory-intensive

3. **Error Handling**
   - SQL errors returned as-is from DuckDB
   - Limited query optimization suggestions
   - No automatic query retry

---

## Troubleshooting

### Common Issues

#### Issue 1: Data Source Not Found

**Error:** `Data source not found: {source_name}`

**Solution:**
- Check configuration file
- Verify source name spelling
- Ensure data source is registered

#### Issue 2: File Not Found

**Error:** `Data file not found: {file_path}`

**Solution:**
- Verify file exists in data directory
- Check file permissions
- Ensure correct file path in config

#### Issue 3: Query Execution Failed

**Error:** `Query execution failed: {error}`

**Solutions:**
- Verify column names exist
- Check SQL syntax
- Ensure data types are compatible
- Review WHERE clause conditions

#### Issue 4: Forbidden Keyword

**Error:** `Query contains forbidden keyword: {keyword}`

**Solution:**
- Remove data modification keywords
- Use only SELECT queries
- Contact administrator for write access

#### Issue 5: Memory Issues

**Symptoms:** Slow performance, crashes

**Solutions:**
- Reduce query result size
- Add more restrictive WHERE clauses
- Use LIMIT clause
- Sample data instead of full tables
- Increase system memory

### Debug Mode

Enable detailed logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Architecture Diagrams

### System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                        │
│                   (MCP Tool Consumer)                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ MCP Protocol
                       │
┌──────────────────────▼──────────────────────────────────────┐
│               SQL Select MCP Tools                           │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │   List     │  │  Describe  │  │  Execute   │            │
│  │  Sources   │  │   Source   │  │   Query    │            │
│  └────────────┘  └────────────┘  └────────────┘            │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐            │
│  │   Sample   │  │    Get     │  │   Count    │            │
│  │    Data    │  │   Schema   │  │    Rows    │            │
│  └────────────┘  └────────────┘  └────────────┘            │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ SQL Queries
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                DuckDB In-Memory Engine                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Data Views/Tables                       │   │
│  │  • customers    • orders    • products    • sales    │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ File I/O
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    File System                               │
│           data/sqlselect/ directory                          │
│  • customers.csv  • orders.csv  • products.csv  • sales.csv  │
└─────────────────────────────────────────────────────────────┘
```

### Query Flow Diagram

```
User Request
     │
     ├─→ [1] Tool Selection
     │        │
     │        └─→ [2] Input Validation
     │                 │
     │                 └─→ [3] DuckDB Query Construction
     │                          │
     │                          └─→ [4] Safety Checks
     │                                   │
     │                                   ├─ Validate SELECT only
     │                                   ├─ Check dangerous keywords
     │                                   └─ Apply LIMIT
     │                                         │
     │                                         └─→ [5] Execute Query
     │                                                  │
     │                                                  └─→ [6] Format Results
     │                                                           │
     └──────────────────────────────────────────────────────────┴─→ JSON Response
```

### Data Flow Architecture

```
┌──────────┐
│   CSV    │──┐
└──────────┘  │
              │
┌──────────┐  │         ┌──────────────┐         ┌──────────┐
│ Parquet  │──┼────────→│   DuckDB     │────────→│  Query   │
└──────────┘  │         │  read_*()    │         │ Processor│
              │         └──────────────┘         └──────────┘
┌──────────┐  │                                       │
│   JSON   │──┘                                       │
└──────────┘                                          │
                                                      ▼
                                               ┌──────────┐
                                               │  Result  │
                                               │Formatter │
                                               └────┬─────┘
                                                    │
                                                    ▼
                                              JSON Output
```

---

## Performance Considerations

### Optimization Tips

1. **Query Optimization**
   ```sql
   -- Use specific columns instead of *
   SELECT customer_id, customer_name 
   FROM customers
   
   -- Add appropriate LIMIT
   LIMIT 100
   
   -- Use WHERE clause to reduce data
   WHERE status = 'active'
   
   -- Create efficient joins
   INNER JOIN instead of LEFT JOIN when appropriate
   ```

2. **Data Loading**
   - Parquet files load faster than CSV
   - Consider converting large CSV files to Parquet
   - Keep frequently accessed data in separate smaller files

3. **Memory Management**
   - Close tool instances when done
   - Limit concurrent tool instances
   - Monitor system memory usage

### Performance Metrics

| Operation | Typical Time | Memory Usage |
|-----------|-------------|--------------|
| List Sources | < 10ms | Minimal |
| Describe Source | < 100ms | Low |
| Get Schema | < 50ms | Low |
| Count Rows | 50-500ms | Low-Medium |
| Sample Data | 100-1000ms | Medium |
| Execute Query | 100ms-5s | Medium-High |

---

## Metadata

### Tool Registry

```python
SQLSELECT_TOOLS = {
    'sqlselect_list_sources': SqlSelectListSourcesTool,
    'sqlselect_describe_source': SqlSelectDescribeSourceTool,
    'sqlselect_execute_query': SqlSelectExecuteQueryTool,
    'sqlselect_sample_data': SqlSelectSampleDataTool,
    'sqlselect_get_schema': SqlSelectGetSchemaTool,
    'sqlselect_count_rows': SqlSelectCountRowsTool
}
```

### Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-10-31 | Initial release |

### Rate Limits

- Default: 100 requests per tool per minute
- Configurable via metadata settings
- No hard limits on local execution

### Cache TTL

| Tool | Cache Duration |
|------|----------------|
| list_sources | 3600s (1 hour) |
| describe_source | 1800s (30 min) |
| get_schema | 3600s (1 hour) |
| count_rows | 300s (5 min) |
| sample_data | 300s (5 min) |
| execute_query | 60s (1 min) |

---

## Support & Resources

### Documentation
- Tool Configuration Files: `*.json` in config directory
- Source Code: `sqlselect_tool_refactored.py`

### Contact Information
- **Author:** Ashutosh Sinha
- **Email:** ajsinha@gmail.com

### Dependencies
- **DuckDB:** https://duckdb.org/
- **Python:** https://python.org/

---

## Legal

**Copyright All rights reserved 2025-2030, Ashutosh Sinha**

This software and documentation are proprietary and confidential. Unauthorized copying, distribution, or use is strictly prohibited.

**Email:** ajsinha@gmail.com

---

*End of Reference Guide*
