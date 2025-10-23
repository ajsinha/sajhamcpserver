# SQL MCP Tool Documentation

## © 2025-2030 Ashutosh Sinha

## Overview
The SQL MCP Tool provides SQLite database operations with pre-configured sample tables for demonstration and testing.

## Configuration
- **Environment Variables:**
  - `SQL_DB_PATH` (default: 'data/sample.db'): Database file path
- SQLite database with sample data
- Automatic table creation on initialization

## Pre-configured Tables

### Customers Table
```sql
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    country TEXT,
    registration_date DATE,
    total_purchases DECIMAL(10,2) DEFAULT 0
)
```

### Products Table
```sql
CREATE TABLE products (
    product_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL,
    category TEXT,
    price DECIMAL(10,2),
    stock_quantity INTEGER,
    supplier TEXT
)
```

## Available Methods

### 1. execute_query
Execute a SQL query.

**Parameters:**
- `query`: SQL query string (required)
- `allow_dangerous` (default: False): Allow DROP, DELETE, TRUNCATE, ALTER operations

**Returns:**
- For SELECT: Results as list of dictionaries, row count
- For other queries: Rows affected, success message

**Safety:**
- Dangerous operations blocked by default
- Set allow_dangerous=True to execute DDL operations

### 2. get_table_schema
Get schema information for a table.

**Parameters:**
- `table_name`: Name of the table (required)

**Returns:**
- Column details (name, type, nullable, default, primary key)
- Column count

### 3. list_tables
List all tables in the database.

**Returns:**
- List of table names
- Table count
- Database path

### 4. get_table_info
Get detailed information about a table.

**Parameters:**
- `table_name`: Name of the table (required)

**Returns:**
- Schema information
- Row count
- Sample rows (first 5)

### 5. search_customers
Search for customers.

**Parameters:**
- `search_term` (optional): Search in name or email
- `country` (optional): Filter by country

**Returns:**
- Matching customer records
- Applied filters

### 6. search_products
Search for products.

**Parameters:**
- `category` (optional): Filter by category
- `min_price` (default: 0): Minimum price
- `max_price` (default: 999999): Maximum price

**Returns:**
- Matching products sorted by price
- Applied filters
- Result count

### 7. get_statistics
Get database statistics.

**Returns:**
- Customer statistics (count, average purchases, total revenue)
- Product statistics (count, average price, inventory value)
- Category breakdown

### 8. insert_record
Insert a new record.

**Parameters:**
- `table`: Table name (required)
- `data`: Dictionary of column-value pairs (required)

**Returns:**
- Success message
- Inserted record ID

### 9. update_record
Update a record.

**Parameters:**
- `table`: Table name (required)
- `data`: Dictionary of column-value pairs to update (required)
- `where`: Dictionary of conditions (required)

**Returns:**
- Success message
- Number of rows affected

### 10. delete_record
Delete a record.

**Parameters:**
- `table`: Table name (required)
- `where`: Dictionary of conditions (required)

**Returns:**
- Success message
- Number of rows affected

## Sample Data

### Sample Customers
- John Doe (USA) - $1,250.50 purchases
- Jane Smith (Canada) - $890.75 purchases
- Bob Johnson (UK) - $2,100.00 purchases
- Alice Brown (Australia) - $650.25 purchases
- Charlie Wilson (Germany) - $1,500.00 purchases

### Sample Products
- Electronics: Laptop Pro, Wireless Mouse, Monitor, Keyboard
- Furniture: Office Chair, Standing Desk
- Stationery: Notebook Set, Pen Pack

## Example Usage
```python
# Execute a query
result = sql_tool.handle_tool_call('execute_query', {
    'query': 'SELECT * FROM customers WHERE country = "USA"'
})

# Get table schema
result = sql_tool.handle_tool_call('get_table_schema', {
    'table_name': 'products'
})

# List all tables
result = sql_tool.handle_tool_call('list_tables', {})

# Search customers
result = sql_tool.handle_tool_call('search_customers', {
    'search_term': 'john',
    'country': 'USA'
})

# Search products by price range
result = sql_tool.handle_tool_call('search_products', {
    'category': 'Electronics',
    'min_price': 100,
    'max_price': 1000
})

# Get statistics
result = sql_tool.handle_tool_call('get_statistics', {})

# Insert a record
result = sql_tool.handle_tool_call('insert_record', {
    'table': 'customers',
    'data': {
        'name': 'New Customer',
        'email': 'new@email.com',
        'country': 'USA',
        'registration_date': '2024-01-15'
    }
})

# Update a record
result = sql_tool.handle_tool_call('update_record', {
    'table': 'products',
    'data': {'price': 29.99},
    'where': {'product_id': 1}
})

# Delete a record
result = sql_tool.handle_tool_call('delete_record', {
    'table': 'customers',
    'where': {'customer_id': 10}
})
```

## SQL Query Examples
```sql
-- Get top customers by purchases
SELECT name, country, total_purchases 
FROM customers 
ORDER BY total_purchases DESC 
LIMIT 5;

-- Get products by category with stock levels
SELECT category, COUNT(*) as product_count, SUM(stock_quantity) as total_stock
FROM products
GROUP BY category;

-- Join customers and calculate metrics
SELECT country, COUNT(*) as customer_count, AVG(total_purchases) as avg_purchase
FROM customers
GROUP BY country;
```

## Safety Features

- Dangerous operations (DROP, DELETE, TRUNCATE, ALTER) blocked by default
- Parameterized queries to prevent SQL injection
- Transaction support for data integrity
- Automatic sample data creation
  - Query result limits to prevent overwhelming responses


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.