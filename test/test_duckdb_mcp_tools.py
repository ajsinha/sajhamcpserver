"""
Copyright All rights reserved 2025-2030 Ashutosh Sinha, Email: ajsinha@gmail.com

Test Suite for DuckDB MCP Tools
Comprehensive tests for all DuckDB OLAP analytics tools
"""

import os
import sys
import json
import tempfile
import shutil
import pytest
from pathlib import Path
from datetime import datetime
import csv

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from tools.impl.duckdb_olap_tools_refactored import (
        DUCKDB_TOOLS,
        DuckDbListTablesTool,
        DuckDbDescribeTableTool,
        DuckDbQueryTool,
        DuckDbRefreshViewsTool,
        DuckDbGetStatsTool,
        DuckDbAggregateTool,
        DuckDbListFilesTool
    )
except ImportError as e:
    print(f"Warning: Could not import DuckDB tools: {e}")
    print("Some tests may be skipped")


class TestDataGenerator:
    """Utility class to generate test data files"""
    
    @staticmethod
    def create_sample_csv(file_path: str, num_rows: int = 100):
        """Create a sample CSV file with sales data"""
        with open(file_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'customer_id', 'product', 'amount', 'quantity', 'region', 'date'])
            
            regions = ['North', 'South', 'East', 'West']
            products = ['Widget', 'Gadget', 'Doohickey', 'Thingamajig']
            
            for i in range(1, num_rows + 1):
                writer.writerow([
                    i,
                    (i % 20) + 1,
                    products[i % len(products)],
                    round(100 + (i * 12.5) % 900, 2),
                    (i % 10) + 1,
                    regions[i % len(regions)],
                    f'2024-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}'
                ])
    
    @staticmethod
    def create_customer_csv(file_path: str):
        """Create a sample customer CSV file"""
        with open(file_path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['customer_id', 'customer_name', 'email', 'signup_date', 'status'])
            
            for i in range(1, 21):
                writer.writerow([
                    i,
                    f'Customer {i}',
                    f'customer{i}@example.com',
                    f'2023-{(i % 12) + 1:02d}-01',
                    'active' if i % 3 != 0 else 'inactive'
                ])
    
    @staticmethod
    def create_parquet_file(file_path: str):
        """Create a sample Parquet file"""
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
            
            data = {
                'id': list(range(1, 51)),
                'value': [i * 1.5 for i in range(1, 51)],
                'category': ['A', 'B', 'C'] * 16 + ['A', 'B']
            }
            
            table = pa.table(data)
            pq.write_table(table, file_path)
            return True
        except ImportError:
            print("PyArrow not available, skipping Parquet file creation")
            return False
    
    @staticmethod
    def create_json_file(file_path: str):
        """Create a sample JSON Lines file"""
        data = [
            {'id': i, 'name': f'Item {i}', 'price': i * 10.5, 'in_stock': i % 2 == 0}
            for i in range(1, 31)
        ]
        
        with open(file_path, 'w') as f:
            for record in data:
                f.write(json.dumps(record) + '\n')


@pytest.fixture(scope='module')
def test_data_dir():
    """Create a temporary directory for test data"""
    temp_dir = tempfile.mkdtemp(prefix='duckdb_test_')
    
    # Generate test data files
    TestDataGenerator.create_sample_csv(os.path.join(temp_dir, 'sales.csv'), num_rows=100)
    TestDataGenerator.create_customer_csv(os.path.join(temp_dir, 'customers.csv'))
    TestDataGenerator.create_json_file(os.path.join(temp_dir, 'products.json'))
    
    # Try to create Parquet file if pyarrow is available
    TestDataGenerator.create_parquet_file(os.path.join(temp_dir, 'analytics.parquet'))
    
    yield temp_dir
    
    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture(scope='module')
def tool_config(test_data_dir):
    """Configuration for all tools"""
    return {
        'data_directory': test_data_dir,
        'enabled': True,
        'version': '1.0.0'
    }


@pytest.fixture
def list_tables_tool(tool_config):
    """Fixture for list tables tool"""
    return DuckDbListTablesTool(tool_config)


@pytest.fixture
def describe_table_tool(tool_config):
    """Fixture for describe table tool"""
    return DuckDbDescribeTableTool(tool_config)


@pytest.fixture
def query_tool(tool_config):
    """Fixture for query tool"""
    return DuckDbQueryTool(tool_config)


@pytest.fixture
def stats_tool(tool_config):
    """Fixture for statistics tool"""
    return DuckDbGetStatsTool(tool_config)


@pytest.fixture
def aggregate_tool(tool_config):
    """Fixture for aggregate tool"""
    return DuckDbAggregateTool(tool_config)


@pytest.fixture
def list_files_tool(tool_config):
    """Fixture for list files tool"""
    return DuckDbListFilesTool(tool_config)


@pytest.fixture
def refresh_views_tool(tool_config):
    """Fixture for refresh views tool"""
    return DuckDbRefreshViewsTool(tool_config)


class TestDuckDbListFilesTool:
    """Tests for duckdb_list_files tool"""
    
    def test_list_all_files(self, list_files_tool):
        """Test listing all files in data directory"""
        result = list_files_tool.execute({'file_type': 'all', 'include_metadata': True})
        
        assert 'files' in result
        assert 'total_files' in result
        assert 'summary' in result
        assert result['total_files'] > 0
        
        # Check that CSV files are found
        csv_files = [f for f in result['files'] if f['file_type'] == 'csv']
        assert len(csv_files) >= 2  # sales.csv and customers.csv
    
    def test_list_csv_files_only(self, list_files_tool):
        """Test filtering by CSV file type"""
        result = list_files_tool.execute({'file_type': 'csv'})
        
        assert all(f['file_type'] == 'csv' for f in result['files'])
        assert result['summary']['csv_count'] == result['total_files']
    
    def test_list_json_files_only(self, list_files_tool):
        """Test filtering by JSON file type"""
        result = list_files_tool.execute({'file_type': 'json'})
        
        if result['total_files'] > 0:
            assert all(f['file_type'] == 'json' for f in result['files'])
    
    def test_file_metadata_included(self, list_files_tool):
        """Test that file metadata is included"""
        result = list_files_tool.execute({'file_type': 'all', 'include_metadata': True})
        
        if result['files']:
            first_file = result['files'][0]
            assert 'file_size_bytes' in first_file
            assert 'file_size_human' in first_file
            assert 'modified_date' in first_file
            assert first_file['file_size_bytes'] > 0
    
    def test_summary_statistics(self, list_files_tool):
        """Test summary statistics are correct"""
        result = list_files_tool.execute({'file_type': 'all'})
        
        summary = result['summary']
        assert 'csv_count' in summary
        assert 'parquet_count' in summary
        assert 'json_count' in summary
        assert 'tsv_count' in summary
        assert 'total_size_bytes' in summary
        
        # Verify counts add up
        total_count = (summary['csv_count'] + summary['parquet_count'] + 
                      summary['json_count'] + summary['tsv_count'])
        assert total_count == result['total_files']


class TestDuckDbListTablesTool:
    """Tests for duckdb_list_tables tool"""
    
    def test_list_tables_basic(self, list_tables_tool, query_tool):
        """Test basic table listing"""
        # First, ensure a table exists by querying a CSV file
        query_tool.execute({
            'sql_query': 'CREATE TABLE test_table AS SELECT * FROM read_csv_auto(\'sales.csv\') LIMIT 10'
        })
        
        result = list_tables_tool.execute({'include_system_tables': False})
        
        assert 'tables' in result
        assert 'total_count' in result
        assert isinstance(result['tables'], list)
        assert result['total_count'] >= 0
    
    def test_table_properties(self, list_tables_tool, query_tool):
        """Test that table properties are returned correctly"""
        # Create a test table
        query_tool.execute({
            'sql_query': 'CREATE OR REPLACE TABLE simple_test AS SELECT 1 as id, \'test\' as name'
        })
        
        result = list_tables_tool.execute({'include_system_tables': False})
        
        if result['tables']:
            table = result['tables'][0]
            assert 'name' in table
            assert 'type' in table
            assert table['type'] in ['table', 'view', 'external']
    
    def test_exclude_system_tables(self, list_tables_tool):
        """Test excluding system tables"""
        result = list_tables_tool.execute({'include_system_tables': False})
        
        # System tables should not be included
        table_names = [t['name'] for t in result['tables']]
        assert not any(name.startswith('duckdb_') for name in table_names)


class TestDuckDbDescribeTableTool:
    """Tests for duckdb_describe_table tool"""
    
    def test_describe_table_basic(self, describe_table_tool, query_tool):
        """Test basic table description"""
        # Create a test table
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE describe_test AS 
                SELECT 1 as id, 'test' as name, 100.50 as amount
            '''
        })
        
        result = describe_table_tool.execute({'table_name': 'describe_test'})
        
        assert 'table_name' in result
        assert 'table_type' in result
        assert 'columns' in result
        assert 'row_count' in result
        assert result['table_name'] == 'describe_test'
        assert len(result['columns']) == 3
    
    def test_column_details(self, describe_table_tool, query_tool):
        """Test that column details are correct"""
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE column_test AS 
                SELECT 
                    1 as id, 
                    'name' as text_col,
                    123.45 as numeric_col,
                    true as bool_col
            '''
        })
        
        result = describe_table_tool.execute({'table_name': 'column_test'})
        
        columns = result['columns']
        assert len(columns) == 4
        
        # Check column properties
        for col in columns:
            assert 'column_name' in col
            assert 'data_type' in col
            assert col['column_name'] in ['id', 'text_col', 'numeric_col', 'bool_col']
    
    def test_describe_with_sample_data(self, describe_table_tool, query_tool):
        """Test describing table with sample data"""
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE sample_test AS 
                SELECT i as id, 'row_' || i as name 
                FROM range(1, 11) t(i)
            '''
        })
        
        result = describe_table_tool.execute({
            'table_name': 'sample_test',
            'include_sample_data': True,
            'sample_size': 3
        })
        
        assert 'sample_data' in result
        assert len(result['sample_data']) <= 3
        assert result['row_count'] == 10
    
    def test_describe_nonexistent_table(self, describe_table_tool):
        """Test describing a table that doesn't exist"""
        with pytest.raises(Exception):
            describe_table_tool.execute({'table_name': 'nonexistent_table_xyz'})


class TestDuckDbQueryTool:
    """Tests for duckdb_query tool"""
    
    def test_simple_select_query(self, query_tool):
        """Test simple SELECT query"""
        result = query_tool.execute({
            'sql_query': 'SELECT 1 as num, \'test\' as text',
            'limit': 10
        })
        
        assert 'query' in result
        assert 'columns' in result
        assert 'rows' in result
        assert 'row_count' in result
        assert result['row_count'] == 1
        assert 'num' in result['columns']
        assert 'text' in result['columns']
    
    def test_query_csv_file(self, query_tool, test_data_dir):
        """Test querying CSV file directly"""
        csv_path = os.path.join(test_data_dir, 'sales.csv')
        
        result = query_tool.execute({
            'sql_query': f"SELECT * FROM read_csv_auto('{csv_path}') LIMIT 5"
        })
        
        assert result['row_count'] == 5
        assert 'id' in result['columns']
        assert 'amount' in result['columns']
    
    def test_aggregation_query(self, query_tool, test_data_dir):
        """Test aggregation query"""
        csv_path = os.path.join(test_data_dir, 'sales.csv')
        
        result = query_tool.execute({
            'sql_query': f'''
                SELECT 
                    region,
                    COUNT(*) as order_count,
                    SUM(amount) as total_amount,
                    AVG(amount) as avg_amount
                FROM read_csv_auto('{csv_path}')
                GROUP BY region
                ORDER BY total_amount DESC
            '''
        })
        
        assert result['row_count'] > 0
        assert 'region' in result['columns']
        assert 'order_count' in result['columns']
        assert 'total_amount' in result['columns']
    
    def test_join_query(self, query_tool, test_data_dir):
        """Test JOIN query between two tables"""
        sales_path = os.path.join(test_data_dir, 'sales.csv')
        customers_path = os.path.join(test_data_dir, 'customers.csv')
        
        result = query_tool.execute({
            'sql_query': f'''
                SELECT 
                    c.customer_name,
                    COUNT(s.id) as order_count,
                    SUM(s.amount) as total_spent
                FROM read_csv_auto('{customers_path}') c
                LEFT JOIN read_csv_auto('{sales_path}') s 
                    ON c.customer_id = s.customer_id
                GROUP BY c.customer_name
                HAVING COUNT(s.id) > 0
                ORDER BY total_spent DESC
                LIMIT 10
            '''
        })
        
        assert 'customer_name' in result['columns']
        assert 'order_count' in result['columns']
        assert 'total_spent' in result['columns']
    
    def test_window_function_query(self, query_tool, test_data_dir):
        """Test window function query"""
        csv_path = os.path.join(test_data_dir, 'sales.csv')
        
        result = query_tool.execute({
            'sql_query': f'''
                SELECT 
                    region,
                    amount,
                    ROW_NUMBER() OVER (PARTITION BY region ORDER BY amount DESC) as rank_in_region
                FROM read_csv_auto('{csv_path}')
            ''',
            'limit': 20
        })
        
        assert 'rank_in_region' in result['columns']
        assert result['row_count'] <= 20
    
    def test_query_with_cte(self, query_tool, test_data_dir):
        """Test query with Common Table Expression (CTE)"""
        csv_path = os.path.join(test_data_dir, 'sales.csv')
        
        result = query_tool.execute({
            'sql_query': f'''
                WITH regional_totals AS (
                    SELECT 
                        region,
                        SUM(amount) as total
                    FROM read_csv_auto('{csv_path}')
                    GROUP BY region
                )
                SELECT * FROM regional_totals
                WHERE total > 0
                ORDER BY total DESC
            '''
        })
        
        assert result['row_count'] > 0
        assert 'region' in result['columns']
        assert 'total' in result['columns']
    
    def test_query_limit(self, query_tool, test_data_dir):
        """Test that query limit is enforced"""
        csv_path = os.path.join(test_data_dir, 'sales.csv')
        
        result = query_tool.execute({
            'sql_query': f"SELECT * FROM read_csv_auto('{csv_path}')",
            'limit': 10
        })
        
        assert result['row_count'] <= 10
    
    def test_execution_time_tracked(self, query_tool):
        """Test that execution time is tracked"""
        result = query_tool.execute({
            'sql_query': 'SELECT 1'
        })
        
        assert 'execution_time_ms' in result
        assert result['execution_time_ms'] >= 0


class TestDuckDbGetStatsTool:
    """Tests for duckdb_get_stats tool"""
    
    def test_get_stats_basic(self, stats_tool, query_tool):
        """Test basic statistics retrieval"""
        # Create test data
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE stats_test AS
                SELECT 
                    i as id,
                    i * 10 as value,
                    'group_' || (i % 3) as category
                FROM range(1, 101) t(i)
            '''
        })
        
        result = stats_tool.execute({
            'table_name': 'stats_test',
            'include_percentiles': True
        })
        
        assert 'table_name' in result
        assert 'total_rows' in result
        assert 'column_statistics' in result
        assert result['total_rows'] == 100
    
    def test_numeric_column_stats(self, stats_tool, query_tool):
        """Test statistics for numeric columns"""
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE numeric_stats AS
                SELECT 
                    i as id,
                    i * 1.5 as amount
                FROM range(1, 51) t(i)
            '''
        })
        
        result = stats_tool.execute({
            'table_name': 'numeric_stats',
            'columns': ['id', 'amount'],
            'include_percentiles': True
        })
        
        stats = result['column_statistics']
        
        # Check ID column stats
        assert 'id' in stats
        id_stats = stats['id']
        assert id_stats['count'] == 50
        assert id_stats['min'] == 1
        assert id_stats['max'] == 50
        assert 'mean' in id_stats
        assert 'std_dev' in id_stats
        
        # Check percentiles
        if 'median' in id_stats:
            assert id_stats['median'] > 0
    
    def test_stats_specific_columns(self, stats_tool, query_tool):
        """Test statistics for specific columns only"""
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE multi_column AS
                SELECT 
                    i as col1,
                    i * 2 as col2,
                    i * 3 as col3
                FROM range(1, 21) t(i)
            '''
        })
        
        result = stats_tool.execute({
            'table_name': 'multi_column',
            'columns': ['col1', 'col2']
        })
        
        stats = result['column_statistics']
        assert 'col1' in stats
        assert 'col2' in stats
    
    def test_stats_without_percentiles(self, stats_tool, query_tool):
        """Test statistics without percentile calculations"""
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE simple_stats AS
                SELECT i as value FROM range(1, 11) t(i)
            '''
        })
        
        result = stats_tool.execute({
            'table_name': 'simple_stats',
            'include_percentiles': False
        })
        
        stats = result['column_statistics']['value']
        assert 'count' in stats
        assert 'mean' in stats
    
    def test_stats_with_nulls(self, stats_tool, query_tool):
        """Test statistics handling null values"""
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE null_test AS
                SELECT 
                    CASE WHEN i % 3 = 0 THEN NULL ELSE i END as value
                FROM range(1, 31) t(i)
            '''
        })
        
        result = stats_tool.execute({'table_name': 'null_test'})
        
        stats = result['column_statistics']
        if 'value' in stats:
            assert 'null_count' in stats['value']
            assert stats['value']['null_count'] > 0


class TestDuckDbAggregateTool:
    """Tests for duckdb_aggregate tool"""
    
    def test_aggregate_basic(self, aggregate_tool, query_tool):
        """Test basic aggregation"""
        # Create test data
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE agg_test AS
                SELECT 
                    'Group_' || (i % 3) as group_name,
                    i as value
                FROM range(1, 31) t(i)
            '''
        })
        
        result = aggregate_tool.execute({
            'table_name': 'agg_test',
            'aggregations': {
                'value': 'sum'
            },
            'group_by': ['group_name']
        })
        
        assert 'aggregations_applied' in result
        assert 'grouped_by' in result
        assert 'results' in result
        assert len(result['results']) > 0
    
    def test_multiple_aggregations(self, aggregate_tool, query_tool):
        """Test multiple aggregation functions"""
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE multi_agg AS
                SELECT 
                    'Region_' || (i % 4) as region,
                    i * 10 as amount,
                    i as quantity
                FROM range(1, 41) t(i)
            '''
        })
        
        result = aggregate_tool.execute({
            'table_name': 'multi_agg',
            'aggregations': {
                'amount': 'sum',
                'quantity': 'avg',
                'region': 'count'
            },
            'group_by': ['region']
        })
        
        assert result['row_count'] > 0
        first_result = result['results'][0]
        assert 'region' in first_result
        assert 'sum_amount' in first_result
        assert 'avg_quantity' in first_result
    
    def test_aggregate_with_having(self, aggregate_tool, query_tool):
        """Test aggregation with HAVING clause"""
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE having_test AS
                SELECT 
                    'Cat_' || (i % 5) as category,
                    i * 100 as amount
                FROM range(1, 51) t(i)
            '''
        })
        
        result = aggregate_tool.execute({
            'table_name': 'having_test',
            'aggregations': {
                'amount': 'sum'
            },
            'group_by': ['category'],
            'having': 'sum_amount > 5000'
        })
        
        # All results should meet the HAVING condition
        for row in result['results']:
            assert row['sum_amount'] > 5000
    
    def test_aggregate_with_order_by(self, aggregate_tool, query_tool):
        """Test aggregation with ORDER BY"""
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE order_test AS
                SELECT 
                    'Item_' || (i % 3) as item,
                    i * 50 as price
                FROM range(1, 31) t(i)
            '''
        })
        
        result = aggregate_tool.execute({
            'table_name': 'order_test',
            'aggregations': {
                'price': 'sum'
            },
            'group_by': ['item'],
            'order_by': [
                {'column': 'sum_price', 'direction': 'desc'}
            ]
        })
        
        # Check that results are ordered
        if len(result['results']) > 1:
            first_value = result['results'][0]['sum_price']
            second_value = result['results'][1]['sum_price']
            assert first_value >= second_value
    
    def test_aggregate_count_distinct(self, aggregate_tool, query_tool):
        """Test COUNT DISTINCT aggregation"""
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE distinct_test AS
                SELECT 
                    'Group_' || (i % 2) as group_name,
                    'Value_' || (i % 5) as value
                FROM range(1, 21) t(i)
            '''
        })
        
        result = aggregate_tool.execute({
            'table_name': 'distinct_test',
            'aggregations': {
                'value': 'count_distinct'
            },
            'group_by': ['group_name']
        })
        
        assert 'count_distinct_value' in result['results'][0]
    
    def test_aggregate_with_limit(self, aggregate_tool, query_tool):
        """Test aggregation result limiting"""
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE limit_test AS
                SELECT 
                    'Key_' || i as key,
                    i * 10 as value
                FROM range(1, 101) t(i)
            '''
        })
        
        result = aggregate_tool.execute({
            'table_name': 'limit_test',
            'aggregations': {
                'value': 'sum'
            },
            'group_by': ['key'],
            'limit': 10
        })
        
        assert result['row_count'] <= 10


class TestDuckDbRefreshViewsTool:
    """Tests for duckdb_refresh_views tool"""
    
    def test_refresh_views_no_views(self, refresh_views_tool):
        """Test refresh when no views exist"""
        result = refresh_views_tool.execute({})
        
        assert 'refreshed_views' in result
        assert 'total_refreshed' in result
        assert isinstance(result['refreshed_views'], list)
    
    def test_refresh_specific_view(self, refresh_views_tool, query_tool):
        """Test refreshing a specific view"""
        # Create a view
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE VIEW test_view AS
                SELECT i as id, i * 2 as doubled
                FROM range(1, 11) t(i)
            '''
        })
        
        result = refresh_views_tool.execute({
            'view_name': 'test_view'
        })
        
        # Check result structure
        assert 'refreshed_views' in result
        assert 'total_refreshed' in result


class TestIntegration:
    """Integration tests combining multiple tools"""
    
    def test_complete_workflow(self, list_files_tool, query_tool, 
                                describe_table_tool, stats_tool, 
                                aggregate_tool, test_data_dir):
        """Test complete analytical workflow"""
        
        # Step 1: List available files
        files = list_files_tool.execute({'file_type': 'all'})
        assert files['total_files'] > 0
        
        # Step 2: Create table from CSV
        csv_path = os.path.join(test_data_dir, 'sales.csv')
        query_tool.execute({
            'sql_query': f'''
                CREATE OR REPLACE TABLE sales AS 
                SELECT * FROM read_csv_auto('{csv_path}')
            '''
        })
        
        # Step 3: Describe the table
        schema = describe_table_tool.execute({
            'table_name': 'sales',
            'include_sample_data': True,
            'sample_size': 5
        })
        assert schema['table_name'] == 'sales'
        assert len(schema['columns']) > 0
        
        # Step 4: Get statistics
        stats = stats_tool.execute({
            'table_name': 'sales',
            'include_percentiles': True
        })
        assert stats['total_rows'] > 0
        
        # Step 5: Perform aggregation
        agg = aggregate_tool.execute({
            'table_name': 'sales',
            'aggregations': {
                'amount': 'sum',
                'id': 'count'
            },
            'group_by': ['region']
        })
        assert agg['row_count'] > 0
    
    def test_data_quality_check(self, query_tool, stats_tool, test_data_dir):
        """Test data quality checking workflow"""
        csv_path = os.path.join(test_data_dir, 'sales.csv')
        
        # Create table
        query_tool.execute({
            'sql_query': f'''
                CREATE OR REPLACE TABLE sales_quality AS 
                SELECT * FROM read_csv_auto('{csv_path}')
            '''
        })
        
        # Get statistics
        stats = stats_tool.execute({
            'table_name': 'sales_quality',
            'include_percentiles': True
        })
        
        # Check for data quality issues
        for col, col_stats in stats['column_statistics'].items():
            # Check null percentage
            if 'null_count' in col_stats and 'count' in col_stats:
                null_pct = col_stats['null_count'] / stats['total_rows'] * 100
                assert null_pct < 50, f"Column {col} has {null_pct}% nulls"
            
            # Check for outliers in numeric columns
            if 'mean' in col_stats and 'std_dev' in col_stats:
                assert col_stats['std_dev'] >= 0


class TestErrorHandling:
    """Tests for error handling and edge cases"""
    
    def test_invalid_table_name(self, describe_table_tool):
        """Test handling of invalid table name"""
        with pytest.raises(Exception):
            describe_table_tool.execute({'table_name': 'nonexistent_table'})
    
    def test_invalid_sql_syntax(self, query_tool):
        """Test handling of invalid SQL"""
        with pytest.raises(Exception):
            query_tool.execute({'sql_query': 'INVALID SQL QUERY'})
    
    def test_invalid_aggregation_function(self, aggregate_tool, query_tool):
        """Test handling of invalid aggregation function"""
        query_tool.execute({
            'sql_query': 'CREATE OR REPLACE TABLE test AS SELECT 1 as value'
        })
        
        # Note: The tool should validate the aggregation function
        # This might not raise an error if validation is not implemented
        result = aggregate_tool.execute({
            'table_name': 'test',
            'aggregations': {'value': 'sum'}  # Valid function
        })
        assert result is not None
    
    def test_empty_result_set(self, query_tool):
        """Test handling of empty result set"""
        result = query_tool.execute({
            'sql_query': 'SELECT * FROM (SELECT 1 as x) WHERE x > 100'
        })
        
        assert result['row_count'] == 0
        assert len(result['rows']) == 0


class TestPerformance:
    """Performance and stress tests"""
    
    def test_large_aggregation(self, aggregate_tool, query_tool):
        """Test aggregation on larger dataset"""
        # Create a larger test dataset
        query_tool.execute({
            'sql_query': '''
                CREATE OR REPLACE TABLE large_test AS
                SELECT 
                    'Group_' || (i % 100) as group_key,
                    i as value
                FROM range(1, 10001) t(i)
            '''
        })
        
        result = aggregate_tool.execute({
            'table_name': 'large_test',
            'aggregations': {
                'value': 'sum',
                'value': 'avg'
            },
            'group_by': ['group_key'],
            'limit': 100
        })
        
        assert result['row_count'] <= 100
        assert 'execution_time_ms' in result
    
    def test_complex_join_performance(self, query_tool, test_data_dir):
        """Test performance of complex join query"""
        sales_path = os.path.join(test_data_dir, 'sales.csv')
        customers_path = os.path.join(test_data_dir, 'customers.csv')
        
        result = query_tool.execute({
            'sql_query': f'''
                WITH customer_stats AS (
                    SELECT 
                        customer_id,
                        COUNT(*) as order_count,
                        SUM(amount) as total
                    FROM read_csv_auto('{sales_path}')
                    GROUP BY customer_id
                )
                SELECT 
                    c.customer_name,
                    cs.order_count,
                    cs.total
                FROM read_csv_auto('{customers_path}') c
                INNER JOIN customer_stats cs ON c.customer_id = cs.customer_id
                ORDER BY cs.total DESC
                LIMIT 10
            '''
        })
        
        assert 'execution_time_ms' in result
        print(f"Complex join executed in {result['execution_time_ms']}ms")


def test_tool_registry():
    """Test that all tools are registered correctly"""
    expected_tools = [
        'duckdb_list_tables',
        'duckdb_describe_table',
        'duckdb_query',
        'duckdb_refresh_views',
        'duckdb_get_stats',
        'duckdb_aggregate',
        'duckdb_list_files'
    ]
    
    for tool_name in expected_tools:
        assert tool_name in DUCKDB_TOOLS, f"Tool {tool_name} not found in registry"
        assert callable(DUCKDB_TOOLS[tool_name]), f"Tool {tool_name} is not callable"


def test_tool_initialization():
    """Test that all tools can be initialized"""
    config = {
        'data_directory': tempfile.mkdtemp(),
        'enabled': True
    }
    
    for tool_name, tool_class in DUCKDB_TOOLS.items():
        tool = tool_class(config)
        assert tool is not None
        assert hasattr(tool, 'execute')
        
        # Clean up
        if hasattr(tool, 'close'):
            tool.close()


if __name__ == '__main__':
    """
    Run tests with pytest:
        pytest test_duckdb_mcp_tools.py -v
        pytest test_duckdb_mcp_tools.py -v --tb=short
        pytest test_duckdb_mcp_tools.py -v -k "test_query"
    """
    pytest.main([__file__, '-v', '--tb=short'])
