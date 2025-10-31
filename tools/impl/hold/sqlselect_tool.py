"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

SQL Select Tool Implementation
This tool provides SQL SELECT query functionality for configured data sources.
Supports CSV, Parquet, and JSON files through DuckDB.
"""

import os
import duckdb
from typing import Dict, Any, List, Optional
from datetime import datetime
from tools.base_mcp_tool import BaseMCPTool


class SqlSelectTool(BaseMCPTool):
    """
    SQL Select Tool for executing SELECT queries on configured data sources.
    
    This tool allows users to:
    - List available data sources
    - Execute SQL SELECT queries
    - Get schema information
    - Retrieve sample data
    - Count rows with filtering
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """
        Initialize the SQL Select Tool.
        
        Args:
            config: Configuration dictionary containing data sources
        """
        super().__init__(config)
        
        self.data_directory = self.config.get('data_directory', 'data/sqlselect')
        self.data_sources = self.config.get('data_sources', {})
        self.connection = None
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Initialize DuckDB connection and load data sources."""
        try:
            # Create in-memory DuckDB connection
            self.connection = duckdb.connect(':memory:')
            
            # Ensure data directory exists
            os.makedirs(self.data_directory, exist_ok=True)
            
            # Register all configured data sources
            self._register_data_sources()
            
            self.logger.info(f"DuckDB connection initialized for {self.name}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize DuckDB connection: {str(e)}")
            raise Exception(f"Failed to initialize DuckDB connection: {str(e)}")
    
    def _register_data_sources(self):
        """Register all configured data sources as DuckDB tables/views."""
        for source_name, source_config in self.data_sources.items():
            try:
                file_path = os.path.join(self.data_directory, source_config['file'])
                file_type = source_config.get('type', 'csv').lower()
                
                if not os.path.exists(file_path):
                    self.logger.warning(f"Data file not found: {file_path}")
                    continue
                
                # Create table/view based on file type
                if file_type == 'csv':
                    self.connection.execute(
                        f"CREATE OR REPLACE VIEW {source_name} AS "
                        f"SELECT * FROM read_csv_auto('{file_path}')"
                    )
                elif file_type == 'parquet':
                    self.connection.execute(
                        f"CREATE OR REPLACE VIEW {source_name} AS "
                        f"SELECT * FROM read_parquet('{file_path}')"
                    )
                elif file_type == 'json':
                    self.connection.execute(
                        f"CREATE OR REPLACE VIEW {source_name} AS "
                        f"SELECT * FROM read_json_auto('{file_path}')"
                    )
                
                self.logger.info(f"Registered data source: {source_name} ({file_type})")
                    
            except Exception as e:
                self.logger.error(f"Error registering data source {source_name}: {str(e)}")
    
    def get_input_schema(self) -> Dict:
        """
        Get the JSON schema for tool inputs.
        
        Returns:
            JSON schema dictionary
        """
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": [
                        "list_sources",
                        "describe_source",
                        "execute_query",
                        "sample_data",
                        "get_schema",
                        "count_rows"
                    ]
                },
                "source_name": {
                    "type": "string",
                    "description": "Name of the data source (required for describe_source, sample_data, get_schema, count_rows)"
                },
                "query": {
                    "type": "string",
                    "description": "SQL SELECT query to execute (required for execute_query)"
                },
                "where_clause": {
                    "type": "string",
                    "description": "WHERE clause for filtering (optional for count_rows)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of rows to return",
                    "default": 100,
                    "minimum": 1,
                    "maximum": 10000
                }
            },
            "required": ["action"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the SQL Select tool with given arguments.
        
        Args:
            arguments: Dictionary containing action and parameters
            
        Returns:
            Dictionary containing execution results
        """
        action = arguments.get('action')
        
        if not action:
            return self._error_response("Action is required")
        
        # Route to appropriate handler
        handlers = {
            'list_sources': self._list_sources,
            'describe_source': self._describe_source,
            'execute_query': self._execute_query,
            'sample_data': self._sample_data,
            'get_schema': self._get_schema,
            'count_rows': self._count_rows
        }
        
        handler = handlers.get(action)
        if not handler:
            return self._error_response(f"Unknown action: {action}")
        
        try:
            return handler(arguments)
        except Exception as e:
            self.logger.error(f"Error executing action {action}: {str(e)}")
            return self._error_response(str(e))
    
    def _list_sources(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """List all available data sources."""
        sources = []
        for source_name, source_config in self.data_sources.items():
            sources.append({
                'name': source_name,
                'file': source_config['file'],
                'type': source_config.get('type', 'csv'),
                'description': source_config.get('description', '')
            })
        
        self.logger.info(f"Listed {len(sources)} data sources")
        
        return {
            'success': True,
            'action': 'list_sources',
            'data': {
                'sources': sources,
                'count': len(sources)
            },
            'timestamp': datetime.now().isoformat()
        }
    
    def _describe_source(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed information about a data source."""
        source_name = arguments.get('source_name')
        
        if not source_name:
            return self._error_response("source_name is required")
        
        if source_name not in self.data_sources:
            return self._error_response(f"Data source not found: {source_name}")
        
        source_config = self.data_sources[source_name]
        
        # Get column information
        try:
            columns_query = f"DESCRIBE {source_name}"
            result = self.connection.execute(columns_query).fetchall()
            columns = [
                {
                    'name': row[0],
                    'type': row[1],
                    'null': row[2],
                    'key': row[3] if len(row) > 3 else None
                }
                for row in result
            ]
        except Exception as e:
            self.logger.error(f"Error getting columns for {source_name}: {str(e)}")
            columns = []
        
        # Get row count
        try:
            count_query = f"SELECT COUNT(*) FROM {source_name}"
            row_count = self.connection.execute(count_query).fetchone()[0]
        except Exception as e:
            self.logger.error(f"Error counting rows for {source_name}: {str(e)}")
            row_count = 0
        
        self.logger.info(f"Described source: {source_name} ({row_count} rows, {len(columns)} columns)")
        
        return {
            'success': True,
            'action': 'describe_source',
            'data': {
                'source_name': source_name,
                'file': source_config['file'],
                'type': source_config.get('type', 'csv'),
                'description': source_config.get('description', ''),
                'row_count': row_count,
                'columns': columns
            },
            'timestamp': datetime.now().isoformat()
        }
    
    def _execute_query(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a SQL SELECT query."""
        query = arguments.get('query')
        limit = arguments.get('limit', 100)
        
        if not query:
            return self._error_response("query is required")
        
        # Validate that query is a SELECT statement
        query_upper = query.strip().upper()
        if not query_upper.startswith('SELECT'):
            return self._error_response("Only SELECT queries are allowed")
        
        # Prevent potentially dangerous keywords
        dangerous_keywords = ['DROP', 'DELETE', 'UPDATE', 'INSERT', 'CREATE', 'ALTER', 'TRUNCATE']
        for keyword in dangerous_keywords:
            if keyword in query_upper:
                return self._error_response(f"Query contains forbidden keyword: {keyword}")
        
        # Add LIMIT if not present
        if 'LIMIT' not in query_upper:
            query = f"{query.strip().rstrip(';')} LIMIT {limit}"
        
        try:
            result = self.connection.execute(query).fetchall()
            columns = [desc[0] for desc in self.connection.description]
            
            # Convert results to list of dictionaries
            data = []
            for row in result:
                data.append(dict(zip(columns, row)))
            
            self.logger.info(f"Executed query: returned {len(data)} rows")
            
            return {
                'success': True,
                'action': 'execute_query',
                'data': {
                    'columns': columns,
                    'rows': data,
                    'row_count': len(data),
                    'query': query
                },
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Query execution failed: {str(e)}")
            return self._error_response(f"Query execution failed: {str(e)}")
    
    def _sample_data(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get sample data from a data source."""
        source_name = arguments.get('source_name')
        limit = arguments.get('limit', 10)
        
        if not source_name:
            return self._error_response("source_name is required")
        
        if source_name not in self.data_sources:
            return self._error_response(f"Data source not found: {source_name}")
        
        query = f"SELECT * FROM {source_name} LIMIT {limit}"
        
        try:
            result = self.connection.execute(query).fetchall()
            columns = [desc[0] for desc in self.connection.description]
            
            data = []
            for row in result:
                data.append(dict(zip(columns, row)))
            
            self.logger.info(f"Retrieved {len(data)} sample rows from {source_name}")
            
            return {
                'success': True,
                'action': 'sample_data',
                'data': {
                    'source_name': source_name,
                    'columns': columns,
                    'rows': data,
                    'row_count': len(data)
                },
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get sample data from {source_name}: {str(e)}")
            return self._error_response(f"Failed to get sample data: {str(e)}")
    
    def _get_schema(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Get schema information for a data source."""
        source_name = arguments.get('source_name')
        
        if not source_name:
            return self._error_response("source_name is required")
        
        if source_name not in self.data_sources:
            return self._error_response(f"Data source not found: {source_name}")
        
        try:
            columns_query = f"DESCRIBE {source_name}"
            result = self.connection.execute(columns_query).fetchall()
            
            schema = []
            for row in result:
                schema.append({
                    'column_name': row[0],
                    'data_type': row[1],
                    'nullable': row[2],
                    'key': row[3] if len(row) > 3 else None
                })
            
            self.logger.info(f"Retrieved schema for {source_name}: {len(schema)} columns")
            
            return {
                'success': True,
                'action': 'get_schema',
                'data': {
                    'source_name': source_name,
                    'schema': schema,
                    'column_count': len(schema)
                },
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get schema for {source_name}: {str(e)}")
            return self._error_response(f"Failed to get schema: {str(e)}")
    
    def _count_rows(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Count rows in a data source with optional WHERE clause."""
        source_name = arguments.get('source_name')
        where_clause = arguments.get('where_clause', '')
        
        if not source_name:
            return self._error_response("source_name is required")
        
        if source_name not in self.data_sources:
            return self._error_response(f"Data source not found: {source_name}")
        
        query = f"SELECT COUNT(*) FROM {source_name}"
        if where_clause:
            query += f" WHERE {where_clause}"
        
        try:
            count = self.connection.execute(query).fetchone()[0]
            
            self.logger.info(f"Counted rows in {source_name}: {count}")
            
            return {
                'success': True,
                'action': 'count_rows',
                'data': {
                    'source_name': source_name,
                    'row_count': count,
                    'where_clause': where_clause if where_clause else None
                },
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to count rows in {source_name}: {str(e)}")
            return self._error_response(f"Failed to count rows: {str(e)}")
    
    def _error_response(self, error_message: str) -> Dict[str, Any]:
        """Generate error response."""
        return {
            'success': False,
            'error': error_message,
            'timestamp': datetime.now().isoformat()
        }
    
    def __del__(self):
        """Close DuckDB connection on cleanup."""
        if self.connection:
            try:
                self.connection.close()
                self.logger.info(f"DuckDB connection closed for {self.name}")
            except:
                pass
