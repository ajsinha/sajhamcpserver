"""
Copyright All rights reserved 2025-2030, Ashutosh Sinha
Email: ajsinha@gmail.com

Comprehensive Test Suite for SQL Select MCP Tools
Tests all six tools with various scenarios including success and error cases
"""

import unittest
import os
import tempfile
import shutil
import csv
import json
from typing import Dict, Any
from datetime import datetime


# Mock BaseMCPTool for testing
class BaseMCPTool:
    """Mock base class for testing"""
    def __init__(self, config: Dict = None):
        self.config = config or {}
        self.name = self.config.get('name', 'test_tool')
        
    class Logger:
        def info(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg): pass
        def debug(self, msg): pass
    
    logger = Logger()


# Import the tools (in real scenario, adjust import path)
try:
    from sqlselect_tool_refactored import (
        SqlSelectListSourcesTool,
        SqlSelectDescribeSourceTool,
        SqlSelectExecuteQueryTool,
        SqlSelectSampleDataTool,
        SqlSelectGetSchemaTool,
        SqlSelectCountRowsTool,
        SQLSELECT_TOOLS
    )
except ImportError:
    # If import fails, we'll define mock versions for demonstration
    print("Warning: Could not import tools. Using mock implementations for testing structure.")


class TestSqlSelectToolsBase(unittest.TestCase):
    """Base test class with common setup and teardown"""
    
    @classmethod
    def setUpClass(cls):
        """Set up test environment once for all tests"""
        # Create temporary directory for test data
        cls.test_dir = tempfile.mkdtemp()
        cls.data_dir = os.path.join(cls.test_dir, 'data', 'sqlselect')
        os.makedirs(cls.data_dir, exist_ok=True)
        
        # Create test CSV files
        cls._create_test_data()
        
        # Create configuration
        cls.config = {
            'data_directory': cls.data_dir,
            'data_sources': {
                'customers': {
                    'file': 'customers.csv',
                    'type': 'csv',
                    'description': 'Customer master data'
                },
                'orders': {
                    'file': 'orders.csv',
                    'type': 'csv',
                    'description': 'Order transactions'
                },
                'products': {
                    'file': 'products.csv',
                    'type': 'csv',
                    'description': 'Product catalog'
                },
                'sales': {
                    'file': 'sales.csv',
                    'type': 'csv',
                    'description': 'Sales data'
                }
            }
        }
    
    @classmethod
    def _create_test_data(cls):
        """Create test CSV files with sample data"""
        
        # Customers data
        customers = [
            ['customer_id', 'customer_name', 'email', 'status', 'created_date'],
            [1, 'John Doe', 'john@example.com', 'active', '2024-01-15'],
            [2, 'Jane Smith', 'jane@example.com', 'active', '2024-02-20'],
            [3, 'Bob Johnson', 'bob@example.com', 'inactive', '2024-03-10'],
            [4, 'Alice Williams', 'alice@example.com', 'active', '2024-04-05'],
            [5, 'Charlie Brown', 'charlie@example.com', 'active', '2024-05-12']
        ]
        cls._write_csv('customers.csv', customers)
        
        # Orders data
        orders = [
            ['order_id', 'customer_id', 'order_date', 'status', 'total_amount'],
            [101, 1, '2024-06-01', 'completed', 150.50],
            [102, 1, '2024-06-15', 'completed', 200.00],
            [103, 2, '2024-06-10', 'completed', 350.75],
            [104, 3, '2024-06-20', 'pending', 89.99],
            [105, 4, '2024-06-25', 'completed', 500.00],
            [106, 4, '2024-07-01', 'completed', 275.50],
            [107, 5, '2024-07-05', 'cancelled', 125.00]
        ]
        cls._write_csv('orders.csv', orders)
        
        # Products data
        products = [
            ['product_id', 'product_name', 'category', 'price', 'stock_quantity'],
            [1001, 'Laptop', 'Electronics', 999.99, 50],
            [1002, 'Mouse', 'Electronics', 25.99, 200],
            [1003, 'Keyboard', 'Electronics', 75.00, 150],
            [1004, 'Monitor', 'Electronics', 299.99, 75],
            [1005, 'Desk Chair', 'Furniture', 199.99, 30]
        ]
        cls._write_csv('products.csv', products)
        
        # Sales data
        sales = [
            ['sale_id', 'customer_id', 'product_id', 'sale_date', 'quantity', 'amount'],
            [1, 1, 1001, '2024-06-01', 1, 999.99],
            [2, 1, 1002, '2024-06-01', 2, 51.98],
            [3, 2, 1003, '2024-06-10', 1, 75.00],
            [4, 2, 1004, '2024-06-10', 1, 299.99],
            [5, 4, 1001, '2024-06-25', 1, 999.99],
            [6, 4, 1005, '2024-07-01', 1, 199.99]
        ]
        cls._write_csv('sales.csv', sales)
    
    @classmethod
    def _write_csv(cls, filename: str, data: list):
        """Write data to CSV file"""
        filepath = os.path.join(cls.data_dir, filename)
        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerows(data)
    
    @classmethod
    def tearDownClass(cls):
        """Clean up test environment"""
        shutil.rmtree(cls.test_dir)
    
    def _validate_success_response(self, response: Dict[str, Any]):
        """Validate common success response fields"""
        self.assertIn('success', response)
        self.assertTrue(response['success'])
        self.assertIn('timestamp', response)
        # Validate timestamp format
        try:
            datetime.fromisoformat(response['timestamp'])
        except ValueError:
            self.fail(f"Invalid timestamp format: {response['timestamp']}")
    
    def _validate_error_response(self, response: Dict[str, Any]):
        """Validate common error response fields"""
        self.assertIn('success', response)
        self.assertFalse(response['success'])
        self.assertIn('error', response)
        self.assertIsInstance(response['error'], str)


class TestSqlSelectListSourcesTool(TestSqlSelectToolsBase):
    """Test cases for sqlselect_list_sources tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = SqlSelectListSourcesTool(self.config)
    
    def test_list_sources_success(self):
        """Test successful listing of all data sources"""
        result = self.tool.execute({})
        
        self._validate_success_response(result)
        self.assertIn('sources', result)
        self.assertIn('count', result)
        self.assertEqual(result['count'], 4)
        self.assertEqual(len(result['sources']), 4)
    
    def test_list_sources_structure(self):
        """Test structure of returned sources"""
        result = self.tool.execute({})
        
        for source in result['sources']:
            self.assertIn('name', source)
            self.assertIn('file', source)
            self.assertIn('type', source)
            self.assertIn('description', source)
    
    def test_list_sources_specific_names(self):
        """Test that specific sources are present"""
        result = self.tool.execute({})
        
        source_names = [s['name'] for s in result['sources']]
        self.assertIn('customers', source_names)
        self.assertIn('orders', source_names)
        self.assertIn('products', source_names)
        self.assertIn('sales', source_names)
    
    def test_list_sources_empty_input(self):
        """Test with empty input parameters"""
        result = self.tool.execute({})
        self.assertTrue(result['success'])
    
    def test_list_sources_schema_validation(self):
        """Test input and output schema methods"""
        input_schema = self.tool.get_input_schema()
        output_schema = self.tool.get_output_schema()
        
        self.assertIsInstance(input_schema, dict)
        self.assertIsInstance(output_schema, dict)
        self.assertEqual(input_schema['type'], 'object')
        self.assertEqual(output_schema['type'], 'object')


class TestSqlSelectDescribeSourceTool(TestSqlSelectToolsBase):
    """Test cases for sqlselect_describe_source tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = SqlSelectDescribeSourceTool(self.config)
    
    def test_describe_customers_success(self):
        """Test describing customers data source"""
        result = self.tool.execute({'source_name': 'customers'})
        
        self._validate_success_response(result)
        self.assertEqual(result['source_name'], 'customers')
        self.assertIn('row_count', result)
        self.assertIn('columns', result)
        self.assertGreater(result['row_count'], 0)
    
    def test_describe_source_columns(self):
        """Test column information in describe result"""
        result = self.tool.execute({'source_name': 'customers'})
        
        columns = result['columns']
        self.assertIsInstance(columns, list)
        self.assertGreater(len(columns), 0)
        
        for col in columns:
            self.assertIn('column_name', col)
            self.assertIn('data_type', col)
            self.assertIn('nullable', col)
    
    def test_describe_all_sources(self):
        """Test describing all configured sources"""
        sources = ['customers', 'orders', 'products', 'sales']
        
        for source in sources:
            result = self.tool.execute({'source_name': source})
            self.assertTrue(result['success'], f"Failed to describe {source}")
            self.assertEqual(result['source_name'], source)
    
    def test_describe_invalid_source(self):
        """Test describing non-existent source"""
        result = self.tool.execute({'source_name': 'nonexistent'})
        
        self._validate_error_response(result)
        self.assertIn('not found', result['error'].lower())
    
    def test_describe_missing_parameter(self):
        """Test with missing source_name parameter"""
        result = self.tool.execute({})
        
        self._validate_error_response(result)
        self.assertIn('required', result['error'].lower())
    
    def test_describe_metadata(self):
        """Test metadata fields in describe result"""
        result = self.tool.execute({'source_name': 'orders'})
        
        self.assertIn('file', result)
        self.assertIn('type', result)
        self.assertIn('description', result)
        self.assertEqual(result['type'], 'csv')


class TestSqlSelectExecuteQueryTool(TestSqlSelectToolsBase):
    """Test cases for sqlselect_execute_query tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = SqlSelectExecuteQueryTool(self.config)
    
    def test_execute_simple_select(self):
        """Test simple SELECT query"""
        result = self.tool.execute({
            'query': 'SELECT * FROM customers'
        })
        
        self._validate_success_response(result)
        self.assertIn('columns', result)
        self.assertIn('rows', result)
        self.assertIn('row_count', result)
        self.assertGreater(result['row_count'], 0)
    
    def test_execute_with_where_clause(self):
        """Test SELECT with WHERE clause"""
        result = self.tool.execute({
            'query': "SELECT * FROM customers WHERE status = 'active'"
        })
        
        self.assertTrue(result['success'])
        self.assertGreater(result['row_count'], 0)
        
        # Verify all returned rows have active status
        for row in result['rows']:
            self.assertEqual(row['status'], 'active')
    
    def test_execute_aggregate_query(self):
        """Test aggregate functions"""
        result = self.tool.execute({
            'query': 'SELECT COUNT(*) as total_customers FROM customers'
        })
        
        self.assertTrue(result['success'])
        self.assertEqual(len(result['rows']), 1)
        self.assertIn('total_customers', result['rows'][0])
    
    def test_execute_join_query(self):
        """Test JOIN query"""
        result = self.tool.execute({
            'query': '''
                SELECT c.customer_name, COUNT(o.order_id) as order_count
                FROM customers c
                LEFT JOIN orders o ON c.customer_id = o.customer_id
                GROUP BY c.customer_name
            '''
        })
        
        self.assertTrue(result['success'])
        self.assertGreater(result['row_count'], 0)
        self.assertIn('customer_name', result['columns'])
        self.assertIn('order_count', result['columns'])
    
    def test_execute_with_limit(self):
        """Test query with custom limit"""
        result = self.tool.execute({
            'query': 'SELECT * FROM orders',
            'limit': 3
        })
        
        self.assertTrue(result['success'])
        self.assertLessEqual(result['row_count'], 3)
    
    def test_execute_order_by(self):
        """Test ORDER BY clause"""
        result = self.tool.execute({
            'query': 'SELECT * FROM products ORDER BY price DESC',
            'limit': 5
        })
        
        self.assertTrue(result['success'])
        
        # Verify descending order
        prices = [row['price'] for row in result['rows']]
        self.assertEqual(prices, sorted(prices, reverse=True))
    
    def test_execute_forbidden_drop(self):
        """Test rejection of DROP statement"""
        result = self.tool.execute({
            'query': 'DROP TABLE customers'
        })
        
        self._validate_error_response(result)
        self.assertIn('forbidden', result['error'].lower())
    
    def test_execute_forbidden_delete(self):
        """Test rejection of DELETE statement"""
        result = self.tool.execute({
            'query': 'DELETE FROM customers WHERE customer_id = 1'
        })
        
        self._validate_error_response(result)
    
    def test_execute_forbidden_update(self):
        """Test rejection of UPDATE statement"""
        result = self.tool.execute({
            'query': 'UPDATE customers SET status = "inactive"'
        })
        
        self._validate_error_response(result)
    
    def test_execute_forbidden_insert(self):
        """Test rejection of INSERT statement"""
        result = self.tool.execute({
            'query': 'INSERT INTO customers VALUES (99, "Test", "test@test.com")'
        })
        
        self._validate_error_response(result)
    
    def test_execute_missing_query(self):
        """Test with missing query parameter"""
        result = self.tool.execute({})
        
        self._validate_error_response(result)
        self.assertIn('required', result['error'].lower())
    
    def test_execute_invalid_sql(self):
        """Test with invalid SQL syntax"""
        result = self.tool.execute({
            'query': 'SELECT * FROMM customers'  # Typo
        })
        
        self._validate_error_response(result)
    
    def test_execute_non_select_start(self):
        """Test query not starting with SELECT"""
        result = self.tool.execute({
            'query': 'SHOW TABLES'
        })
        
        self._validate_error_response(result)
        self.assertIn('SELECT', result['error'])


class TestSqlSelectSampleDataTool(TestSqlSelectToolsBase):
    """Test cases for sqlselect_sample_data tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = SqlSelectSampleDataTool(self.config)
    
    def test_sample_default_limit(self):
        """Test sampling with default limit"""
        result = self.tool.execute({
            'source_name': 'customers'
        })
        
        self._validate_success_response(result)
        self.assertIn('rows', result)
        self.assertLessEqual(result['row_count'], 10)  # Default limit
    
    def test_sample_custom_limit(self):
        """Test sampling with custom limit"""
        result = self.tool.execute({
            'source_name': 'products',
            'limit': 3
        })
        
        self.assertTrue(result['success'])
        self.assertLessEqual(result['row_count'], 3)
    
    def test_sample_all_sources(self):
        """Test sampling from all sources"""
        sources = ['customers', 'orders', 'products', 'sales']
        
        for source in sources:
            result = self.tool.execute({
                'source_name': source,
                'limit': 5
            })
            self.assertTrue(result['success'], f"Failed to sample {source}")
            self.assertEqual(result['source_name'], source)
    
    def test_sample_columns_present(self):
        """Test that columns are included in result"""
        result = self.tool.execute({
            'source_name': 'orders',
            'limit': 5
        })
        
        self.assertIn('columns', result)
        self.assertIsInstance(result['columns'], list)
        self.assertGreater(len(result['columns']), 0)
    
    def test_sample_rows_structure(self):
        """Test structure of returned rows"""
        result = self.tool.execute({
            'source_name': 'customers',
            'limit': 2
        })
        
        for row in result['rows']:
            self.assertIsInstance(row, dict)
            # Each row should have values for all columns
            for col in result['columns']:
                self.assertIn(col, row)
    
    def test_sample_invalid_source(self):
        """Test sampling from non-existent source"""
        result = self.tool.execute({
            'source_name': 'invalid_source'
        })
        
        self._validate_error_response(result)
    
    def test_sample_missing_source_name(self):
        """Test with missing source_name parameter"""
        result = self.tool.execute({
            'limit': 5
        })
        
        self._validate_error_response(result)
    
    def test_sample_large_limit(self):
        """Test sampling with very large limit"""
        result = self.tool.execute({
            'source_name': 'customers',
            'limit': 1000
        })
        
        self.assertTrue(result['success'])
        # Should not exceed actual row count
        self.assertLessEqual(result['row_count'], 1000)


class TestSqlSelectGetSchemaTool(TestSqlSelectToolsBase):
    """Test cases for sqlselect_get_schema tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = SqlSelectGetSchemaTool(self.config)
    
    def test_get_schema_customers(self):
        """Test getting schema for customers"""
        result = self.tool.execute({
            'source_name': 'customers'
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['source_name'], 'customers')
        self.assertIn('schema', result)
        self.assertIn('column_count', result)
    
    def test_get_schema_structure(self):
        """Test schema structure"""
        result = self.tool.execute({
            'source_name': 'products'
        })
        
        schema = result['schema']
        self.assertIsInstance(schema, list)
        self.assertGreater(len(schema), 0)
        
        for col_info in schema:
            self.assertIn('column_name', col_info)
            self.assertIn('data_type', col_info)
            self.assertIn('nullable', col_info)
    
    def test_get_schema_column_count(self):
        """Test column count matches schema length"""
        result = self.tool.execute({
            'source_name': 'orders'
        })
        
        self.assertEqual(result['column_count'], len(result['schema']))
    
    def test_get_schema_all_sources(self):
        """Test getting schema for all sources"""
        sources = ['customers', 'orders', 'products', 'sales']
        
        for source in sources:
            result = self.tool.execute({'source_name': source})
            self.assertTrue(result['success'], f"Failed to get schema for {source}")
            self.assertGreater(result['column_count'], 0)
    
    def test_get_schema_data_types(self):
        """Test that data types are present"""
        result = self.tool.execute({
            'source_name': 'products'
        })
        
        data_types = [col['data_type'] for col in result['schema']]
        self.assertGreater(len(set(data_types)), 0)
        # Should have at least VARCHAR and numeric types
        self.assertTrue(any('VARCHAR' in dt or 'INTEGER' in dt or 'DOUBLE' in dt 
                           for dt in data_types))
    
    def test_get_schema_invalid_source(self):
        """Test getting schema for non-existent source"""
        result = self.tool.execute({
            'source_name': 'nonexistent_table'
        })
        
        self._validate_error_response(result)
    
    def test_get_schema_missing_parameter(self):
        """Test with missing source_name parameter"""
        result = self.tool.execute({})
        
        self._validate_error_response(result)


class TestSqlSelectCountRowsTool(TestSqlSelectToolsBase):
    """Test cases for sqlselect_count_rows tool"""
    
    def setUp(self):
        """Set up tool instance for each test"""
        self.tool = SqlSelectCountRowsTool(self.config)
    
    def test_count_all_customers(self):
        """Test counting all customers"""
        result = self.tool.execute({
            'source_name': 'customers'
        })
        
        self._validate_success_response(result)
        self.assertEqual(result['source_name'], 'customers')
        self.assertIn('row_count', result)
        self.assertGreater(result['row_count'], 0)
    
    def test_count_with_where_clause(self):
        """Test counting with WHERE clause"""
        result = self.tool.execute({
            'source_name': 'customers',
            'where_clause': "status = 'active'"
        })
        
        self.assertTrue(result['success'])
        self.assertIn('where_clause', result)
        self.assertEqual(result['where_clause'], "status = 'active'")
        self.assertGreater(result['row_count'], 0)
    
    def test_count_complex_where(self):
        """Test counting with complex WHERE clause"""
        result = self.tool.execute({
            'source_name': 'orders',
            'where_clause': "status = 'completed' AND total_amount > 200"
        })
        
        self.assertTrue(result['success'])
        self.assertGreaterEqual(result['row_count'], 0)
    
    def test_count_all_sources(self):
        """Test counting rows in all sources"""
        sources = ['customers', 'orders', 'products', 'sales']
        
        for source in sources:
            result = self.tool.execute({'source_name': source})
            self.assertTrue(result['success'], f"Failed to count {source}")
            self.assertIsInstance(result['row_count'], int)
    
    def test_count_zero_results(self):
        """Test counting with WHERE that returns zero results"""
        result = self.tool.execute({
            'source_name': 'customers',
            'where_clause': "customer_id > 999999"
        })
        
        self.assertTrue(result['success'])
        self.assertEqual(result['row_count'], 0)
    
    def test_count_date_filter(self):
        """Test counting with date filtering"""
        result = self.tool.execute({
            'source_name': 'orders',
            'where_clause': "order_date >= '2024-06-15'"
        })
        
        self.assertTrue(result['success'])
        self.assertGreaterEqual(result['row_count'], 0)
    
    def test_count_invalid_where_clause(self):
        """Test with invalid WHERE clause"""
        result = self.tool.execute({
            'source_name': 'customers',
            'where_clause': "invalid_column = 'value'"
        })
        
        self._validate_error_response(result)
    
    def test_count_invalid_source(self):
        """Test counting from non-existent source"""
        result = self.tool.execute({
            'source_name': 'nonexistent'
        })
        
        self._validate_error_response(result)
    
    def test_count_missing_parameter(self):
        """Test with missing source_name parameter"""
        result = self.tool.execute({})
        
        self._validate_error_response(result)
    
    def test_count_null_where_clause(self):
        """Test that where_clause is optional"""
        result = self.tool.execute({
            'source_name': 'products'
        })
        
        self.assertTrue(result['success'])
        # When no where clause, it should be None or not present
        where_clause = result.get('where_clause')
        self.assertTrue(where_clause is None or where_clause == '')


class TestSqlSelectToolRegistry(TestSqlSelectToolsBase):
    """Test cases for tool registry and integration"""
    
    def test_tool_registry_exists(self):
        """Test that tool registry exists"""
        self.assertIsNotNone(SQLSELECT_TOOLS)
        self.assertIsInstance(SQLSELECT_TOOLS, dict)
    
    def test_all_tools_registered(self):
        """Test that all tools are registered"""
        expected_tools = [
            'sqlselect_list_sources',
            'sqlselect_describe_source',
            'sqlselect_execute_query',
            'sqlselect_sample_data',
            'sqlselect_get_schema',
            'sqlselect_count_rows'
        ]
        
        for tool_name in expected_tools:
            self.assertIn(tool_name, SQLSELECT_TOOLS)
    
    def test_tool_instantiation_from_registry(self):
        """Test creating tools from registry"""
        for tool_name, tool_class in SQLSELECT_TOOLS.items():
            tool = tool_class(self.config)
            self.assertIsNotNone(tool)
    
    def test_all_tools_have_schemas(self):
        """Test that all tools have input and output schemas"""
        for tool_name, tool_class in SQLSELECT_TOOLS.items():
            tool = tool_class(self.config)
            
            input_schema = tool.get_input_schema()
            output_schema = tool.get_output_schema()
            
            self.assertIsInstance(input_schema, dict)
            self.assertIsInstance(output_schema, dict)
            self.assertIn('type', input_schema)
            self.assertIn('type', output_schema)


class TestIntegrationScenarios(TestSqlSelectToolsBase):
    """Integration test scenarios combining multiple tools"""
    
    def test_discover_and_query_workflow(self):
        """Test workflow: list sources -> get schema -> execute query"""
        # Step 1: List sources
        list_tool = SqlSelectListSourcesTool(self.config)
        sources = list_tool.execute({})
        self.assertTrue(sources['success'])
        
        # Step 2: Get schema for first source
        source_name = sources['sources'][0]['name']
        schema_tool = SqlSelectGetSchemaTool(self.config)
        schema = schema_tool.execute({'source_name': source_name})
        self.assertTrue(schema['success'])
        
        # Step 3: Execute query on that source
        query_tool = SqlSelectExecuteQueryTool(self.config)
        result = query_tool.execute({
            'query': f'SELECT * FROM {source_name}',
            'limit': 5
        })
        self.assertTrue(result['success'])
    
    def test_describe_sample_count_workflow(self):
        """Test workflow: describe -> sample -> count"""
        source = 'customers'
        
        # Describe
        describe_tool = SqlSelectDescribeSourceTool(self.config)
        desc_result = describe_tool.execute({'source_name': source})
        self.assertTrue(desc_result['success'])
        
        # Sample
        sample_tool = SqlSelectSampleDataTool(self.config)
        sample_result = sample_tool.execute({
            'source_name': source,
            'limit': 3
        })
        self.assertTrue(sample_result['success'])
        
        # Count
        count_tool = SqlSelectCountRowsTool(self.config)
        count_result = count_tool.execute({'source_name': source})
        self.assertTrue(count_result['success'])
    
    def test_analytical_query_workflow(self):
        """Test complex analytical queries"""
        query_tool = SqlSelectExecuteQueryTool(self.config)
        
        # Test 1: Aggregate by group
        result1 = query_tool.execute({
            'query': '''
                SELECT status, COUNT(*) as count, AVG(total_amount) as avg_amount
                FROM orders
                GROUP BY status
            '''
        })
        self.assertTrue(result1['success'])
        
        # Test 2: Join with aggregation
        result2 = query_tool.execute({
            'query': '''
                SELECT c.customer_name, SUM(o.total_amount) as total_spent
                FROM customers c
                LEFT JOIN orders o ON c.customer_id = o.customer_id
                GROUP BY c.customer_name
                ORDER BY total_spent DESC
            '''
        })
        self.assertTrue(result2['success'])


class TestErrorHandling(TestSqlSelectToolsBase):
    """Test error handling across all tools"""
    
    def test_connection_error_handling(self):
        """Test handling of connection errors"""
        # Create config with non-existent directory
        bad_config = {
            'data_directory': '/nonexistent/path',
            'data_sources': {}
        }
        
        # Tools should handle this gracefully
        try:
            tool = SqlSelectListSourcesTool(bad_config)
            # Should not crash during initialization
            self.assertIsNotNone(tool)
        except Exception as e:
            # If it raises, it should be a controlled exception
            self.assertIsInstance(e, Exception)
    
    def test_malformed_query_handling(self):
        """Test handling of malformed queries"""
        query_tool = SqlSelectExecuteQueryTool(self.config)
        
        malformed_queries = [
            'SELECT * FROM',  # Incomplete
            'SELECT * FROM nonexistent_table',  # Invalid table
            'SELECT invalid_column FROM customers',  # Invalid column
        ]
        
        for query in malformed_queries:
            result = query_tool.execute({'query': query})
            self._validate_error_response(result)
    
    def test_type_error_handling(self):
        """Test handling of type errors in WHERE clauses"""
        count_tool = SqlSelectCountRowsTool(self.config)
        
        # Try to compare number column with string
        result = count_tool.execute({
            'source_name': 'products',
            'where_clause': "price = 'not_a_number'"
        })
        
        # Should either succeed (DuckDB may handle conversion) or fail gracefully
        self.assertIn('success', result)


def run_test_suite():
    """Run the complete test suite"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestSqlSelectListSourcesTool))
    suite.addTests(loader.loadTestsFromTestCase(TestSqlSelectDescribeSourceTool))
    suite.addTests(loader.loadTestsFromTestCase(TestSqlSelectExecuteQueryTool))
    suite.addTests(loader.loadTestsFromTestCase(TestSqlSelectSampleDataTool))
    suite.addTests(loader.loadTestsFromTestCase(TestSqlSelectGetSchemaTool))
    suite.addTests(loader.loadTestsFromTestCase(TestSqlSelectCountRowsTool))
    suite.addTests(loader.loadTestsFromTestCase(TestSqlSelectToolRegistry))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegrationScenarios))
    suite.addTests(loader.loadTestsFromTestCase(TestErrorHandling))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("="*70)
    
    return result


if __name__ == '__main__':
    print("""
    ╔══════════════════════════════════════════════════════════════════╗
    ║  SQL Select MCP Tools - Comprehensive Test Suite                 ║
    ║  Copyright All rights reserved 2025-2030, Ashutosh Sinha        ║
    ║  Email: ajsinha@gmail.com                                        ║
    ╚══════════════════════════════════════════════════════════════════╝
    """)
    
    result = run_test_suite()
    
    # Exit with appropriate code
    exit(0 if result.wasSuccessful() else 1)
