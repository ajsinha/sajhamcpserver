#!/usr/bin/env python3
"""
SAJHA MCP Server - DuckDB Analytics Tools Client v2.2.0

Copyright © 2025-2030, All Rights Reserved
Ashutosh Sinha
Email: ajsinha@gmail.com

Example client for DuckDB OLAP tools:
- duckdb_list_tables: List available tables
- duckdb_describe_table: Get table schema
- duckdb_query: Execute SQL queries
- duckdb_aggregate: Run aggregations
- duckdb_get_stats: Get table statistics
- duckdb_list_files: List data files
- duckdb_refresh_views: Refresh materialized views

Usage:
    export SAJHA_API_KEY="sja_your_key_here"
    python -m sajha.examples.duckdb_client
"""

from base_client import SajhaClient, SajhaAPIError, pretty_print, run_example


class DuckDBClient(SajhaClient):
    """Client for DuckDB analytics tools."""
    
    def list_tables(self) -> dict:
        """List all available tables and views."""
        return self.execute_tool('duckdb_list_tables', {})
    
    def describe_table(self, table_name: str) -> dict:
        """
        Get table schema and structure.
        
        Args:
            table_name: Name of the table
        """
        return self.execute_tool('duckdb_describe_table', {
            'table_name': table_name
        })
    
    def query(self, sql: str, limit: int = 100) -> dict:
        """
        Execute SQL query.
        
        Args:
            sql: SQL query string
            limit: Maximum rows to return
        """
        return self.execute_tool('duckdb_query', {
            'sql': sql,
            'limit': limit
        })
    
    def aggregate(self, 
                  table_name: str,
                  group_by: list = None,
                  aggregations: dict = None,
                  filters: dict = None) -> dict:
        """
        Run aggregation query.
        
        Args:
            table_name: Table to aggregate
            group_by: Columns to group by
            aggregations: Dict of {column: function} (sum, avg, count, min, max)
            filters: Dict of {column: value} filters
        """
        args = {'table_name': table_name}
        if group_by:
            args['group_by'] = group_by
        if aggregations:
            args['aggregations'] = aggregations
        if filters:
            args['filters'] = filters
        return self.execute_tool('duckdb_aggregate', args)
    
    def get_stats(self, table_name: str) -> dict:
        """
        Get table statistics.
        
        Args:
            table_name: Table name
        """
        return self.execute_tool('duckdb_get_stats', {
            'table_name': table_name
        })
    
    def list_files(self, path: str = None) -> dict:
        """
        List data files available for querying.
        
        Args:
            path: Optional path filter
        """
        args = {}
        if path:
            args['path'] = path
        return self.execute_tool('duckdb_list_files', args)
    
    def refresh_views(self) -> dict:
        """Refresh all materialized views."""
        return self.execute_tool('duckdb_refresh_views', {})


@run_example
def example_list_tables():
    """Example: List available tables"""
    client = DuckDBClient()
    
    print("\n📋 Listing available tables...")
    tables = client.list_tables()
    pretty_print(tables, "Available Tables")


@run_example
def example_describe_table():
    """Example: Describe table schema"""
    client = DuckDBClient()
    
    # First get tables list
    tables = client.list_tables()
    
    if tables.get('tables'):
        table_name = tables['tables'][0].get('name', 'data')
        print(f"\n📝 Describing table: {table_name}...")
        schema = client.describe_table(table_name)
        pretty_print(schema, f"Schema: {table_name}")


@run_example
def example_simple_query():
    """Example: Execute simple SQL query"""
    client = DuckDBClient()
    
    print("\n🔍 Running SQL query...")
    
    # First check what tables exist
    tables = client.list_tables()
    
    if tables.get('tables'):
        table_name = tables['tables'][0].get('name', '')
        if table_name:
            sql = f"SELECT * FROM {table_name} LIMIT 5"
            print(f"   Query: {sql}")
            result = client.query(sql, limit=5)
            pretty_print(result, "Query Results")


@run_example
def example_aggregation():
    """Example: Run aggregation"""
    client = DuckDBClient()
    
    print("\n📊 Running aggregation...")
    
    # First check what tables exist
    tables = client.list_tables()
    
    if tables.get('tables'):
        table_name = tables['tables'][0].get('name', '')
        if table_name:
            # Get table stats first
            stats = client.get_stats(table_name)
            pretty_print(stats, f"Stats: {table_name}")


@run_example
def example_get_table_stats():
    """Example: Get table statistics"""
    client = DuckDBClient()
    
    print("\n📈 Getting table statistics...")
    
    tables = client.list_tables()
    
    if tables.get('tables'):
        for table in tables['tables'][:3]:
            table_name = table.get('name', '')
            if table_name:
                print(f"\n   Table: {table_name}")
                try:
                    stats = client.get_stats(table_name)
                    print(f"   Rows: {stats.get('row_count', 'N/A')}")
                    print(f"   Columns: {stats.get('column_count', 'N/A')}")
                except Exception as e:
                    print(f"   Error: {e}")


@run_example
def example_analytics_workflow():
    """Example: Complete analytics workflow"""
    client = DuckDBClient()
    
    print("\n🔬 Analytics Workflow")
    print("=" * 50)
    
    # Step 1: List available data
    print("\n1️⃣ Available tables:")
    tables = client.list_tables()
    
    if tables.get('tables'):
        for t in tables['tables'][:5]:
            print(f"   - {t.get('name')}: {t.get('type', 'table')}")
        
        # Step 2: Describe first table
        if tables['tables']:
            table_name = tables['tables'][0].get('name', '')
            if table_name:
                print(f"\n2️⃣ Schema for {table_name}:")
                schema = client.describe_table(table_name)
                if schema.get('columns'):
                    for col in schema['columns'][:10]:
                        print(f"   - {col.get('name')}: {col.get('type')}")
                
                # Step 3: Sample data
                print(f"\n3️⃣ Sample data from {table_name}:")
                sample = client.query(f"SELECT * FROM {table_name} LIMIT 3")
                if sample.get('rows'):
                    for row in sample['rows'][:3]:
                        print(f"   {row}")


if __name__ == '__main__':
    print("=" * 60)
    print(" SAJHA MCP Server - DuckDB Analytics Tools Examples v2.2.0")
    print("=" * 60)
    
    example_list_tables()
    example_describe_table()
    example_simple_query()
    example_aggregation()
    example_get_table_stats()
    example_analytics_workflow()
