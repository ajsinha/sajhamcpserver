"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
SQL Select MCP Tool Implementation - Refactored with Individual Tools
"""

import os
import duckdb
from typing import Dict, Any, List, Optional
from datetime import datetime
from sajha.tools.base_mcp_tool import BaseMCPTool


class SqlSelectBaseTool(BaseMCPTool):
    """
    Base class for SQL Select tools with shared DuckDB functionality
    """
    
    def __init__(self, config: Dict = None):
        """Initialize SQL Select base tool"""
        super().__init__(config)
        
        self.data_directory = self.config.get('data_directory', 'data/sqlselect')
        self.data_sources = self.config.get('data_sources', {})
        self.connection = None
        self._initialize_connection()
    
    def _initialize_connection(self):
        """Initialize DuckDB connection and load data sources"""
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
        """Register all configured data sources as DuckDB tables/views"""
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
    
    def _error_response(self, error_message: str) -> Dict[str, Any]:
        """Generate error response"""
        return {
            'success': False,
            'error': error_message,
            'timestamp': datetime.now().isoformat()
        }
    
    def __del__(self):
        """Close DuckDB connection on cleanup"""
        if self.connection:
            try:
                self.connection.close()
                self.logger.info(f"DuckDB connection closed for {self.name}")
            except:
                pass


class SqlSelectListSourcesTool(SqlSelectBaseTool):
    """
    Tool to list all available data sources
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sqlselect_list_sources',
            'description': 'List all available data sources with their metadata',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for listing sources"""
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for source list"""
        return {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                    "description": "Whether the operation was successful"
                },
                "sources": {
                    "type": "array",
                    "description": "List of available data sources",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Data source name"
                            },
                            "file": {
                                "type": "string",
                                "description": "Source file name"
                            },
                            "type": {
                                "type": "string",
                                "description": "File type (csv, parquet, json)"
                            },
                            "description": {
                                "type": "string",
                                "description": "Source description"
                            }
                        }
                    }
                },
                "count": {
                    "type": "integer",
                    "description": "Number of available sources"
                },
                "timestamp": {
                    "type": "string",
                    "description": "ISO timestamp of response"
                }
            },
            "required": ["success", "sources", "count", "timestamp"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute list sources operation"""
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
            'sources': sources,
            'count': len(sources),
            'timestamp': datetime.now().isoformat()
        }


class SqlSelectDescribeSourceTool(SqlSelectBaseTool):
    """
    Tool to get detailed information about a specific data source
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sqlselect_describe_source',
            'description': 'Get detailed information about a data source including columns and row count',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for describing source"""
        return {
            "type": "object",
            "properties": {
                "source_name": {
                    "type": "string",
                    "description": "Name of the data source to describe"
                }
            },
            "required": ["source_name"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for source description"""
        return {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                    "description": "Operation success status"
                },
                "source_name": {
                    "type": "string",
                    "description": "Data source name"
                },
                "file": {
                    "type": "string",
                    "description": "Source file name"
                },
                "type": {
                    "type": "string",
                    "description": "File type"
                },
                "description": {
                    "type": "string",
                    "description": "Source description"
                },
                "row_count": {
                    "type": "integer",
                    "description": "Total number of rows"
                },
                "columns": {
                    "type": "array",
                    "description": "Column information",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column_name": {
                                "type": "string"
                            },
                            "data_type": {
                                "type": "string"
                            },
                            "nullable": {
                                "type": "string"
                            },
                            "key": {
                                "type": ["string", "null"]
                            }
                        }
                    }
                },
                "timestamp": {
                    "type": "string",
                    "description": "ISO timestamp"
                }
            },
            "required": ["success", "source_name", "row_count", "columns"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute describe source operation"""
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
                    'column_name': row[0],
                    'data_type': row[1],
                    'nullable': row[2],
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
            'source_name': source_name,
            'file': source_config['file'],
            'type': source_config.get('type', 'csv'),
            'description': source_config.get('description', ''),
            'row_count': row_count,
            'columns': columns,
            'timestamp': datetime.now().isoformat()
        }


class SqlSelectExecuteQueryTool(SqlSelectBaseTool):
    """
    Tool to execute SQL SELECT queries on data sources
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sqlselect_execute_query',
            'description': 'Execute SQL SELECT queries on configured data sources with safety checks',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for query execution"""
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL SELECT query to execute"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of rows to return",
                    "default": 100,
                    "minimum": 1,
                    "maximum": 10000
                }
            },
            "required": ["query"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for query results"""
        return {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                    "description": "Query execution status"
                },
                "columns": {
                    "type": "array",
                    "description": "Column names",
                    "items": {
                        "type": "string"
                    }
                },
                "rows": {
                    "type": "array",
                    "description": "Query result rows",
                    "items": {
                        "type": "object",
                        "description": "Row data as key-value pairs"
                    }
                },
                "row_count": {
                    "type": "integer",
                    "description": "Number of rows returned"
                },
                "query": {
                    "type": "string",
                    "description": "The executed query"
                },
                "timestamp": {
                    "type": "string",
                    "description": "ISO timestamp"
                }
            },
            "required": ["success", "columns", "rows", "row_count"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute SQL SELECT query"""
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
                'columns': columns,
                'rows': data,
                'row_count': len(data),
                'query': query,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Query execution failed: {str(e)}")
            return self._error_response(f"Query execution failed: {str(e)}")


class SqlSelectSampleDataTool(SqlSelectBaseTool):
    """
    Tool to retrieve sample data from a data source
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sqlselect_sample_data',
            'description': 'Retrieve sample rows from a data source for preview and exploration',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for sampling data"""
        return {
            "type": "object",
            "properties": {
                "source_name": {
                    "type": "string",
                    "description": "Name of the data source"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of sample rows to return",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 1000
                }
            },
            "required": ["source_name"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for sample data"""
        return {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                    "description": "Operation status"
                },
                "source_name": {
                    "type": "string",
                    "description": "Data source name"
                },
                "columns": {
                    "type": "array",
                    "description": "Column names",
                    "items": {
                        "type": "string"
                    }
                },
                "rows": {
                    "type": "array",
                    "description": "Sample data rows",
                    "items": {
                        "type": "object"
                    }
                },
                "row_count": {
                    "type": "integer",
                    "description": "Number of sample rows"
                },
                "timestamp": {
                    "type": "string",
                    "description": "ISO timestamp"
                }
            },
            "required": ["success", "source_name", "columns", "rows", "row_count"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute sample data retrieval"""
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
                'source_name': source_name,
                'columns': columns,
                'rows': data,
                'row_count': len(data),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get sample data from {source_name}: {str(e)}")
            return self._error_response(f"Failed to get sample data: {str(e)}")


class SqlSelectGetSchemaTool(SqlSelectBaseTool):
    """
    Tool to get schema information for a data source
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sqlselect_get_schema',
            'description': 'Get detailed schema information including column types and constraints',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for schema retrieval"""
        return {
            "type": "object",
            "properties": {
                "source_name": {
                    "type": "string",
                    "description": "Name of the data source"
                }
            },
            "required": ["source_name"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for schema information"""
        return {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                    "description": "Operation status"
                },
                "source_name": {
                    "type": "string",
                    "description": "Data source name"
                },
                "schema": {
                    "type": "array",
                    "description": "Schema definition",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column_name": {
                                "type": "string",
                                "description": "Column name"
                            },
                            "data_type": {
                                "type": "string",
                                "description": "Data type"
                            },
                            "nullable": {
                                "type": "string",
                                "description": "Nullable status"
                            },
                            "key": {
                                "type": ["string", "null"],
                                "description": "Key constraint"
                            }
                        }
                    }
                },
                "column_count": {
                    "type": "integer",
                    "description": "Number of columns"
                },
                "timestamp": {
                    "type": "string",
                    "description": "ISO timestamp"
                }
            },
            "required": ["success", "source_name", "schema", "column_count"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute schema retrieval"""
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
                'source_name': source_name,
                'schema': schema,
                'column_count': len(schema),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get schema for {source_name}: {str(e)}")
            return self._error_response(f"Failed to get schema: {str(e)}")


class SqlSelectCountRowsTool(SqlSelectBaseTool):
    """
    Tool to count rows in a data source with optional filtering
    """
    
    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'sqlselect_count_rows',
            'description': 'Count rows in a data source with optional WHERE clause filtering',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
    
    def get_input_schema(self) -> Dict:
        """Get input schema for row counting"""
        return {
            "type": "object",
            "properties": {
                "source_name": {
                    "type": "string",
                    "description": "Name of the data source"
                },
                "where_clause": {
                    "type": "string",
                    "description": "Optional WHERE clause for filtering (without 'WHERE' keyword)"
                }
            },
            "required": ["source_name"]
        }
    
    def get_output_schema(self) -> Dict:
        """Get output schema for row count"""
        return {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                    "description": "Operation status"
                },
                "source_name": {
                    "type": "string",
                    "description": "Data source name"
                },
                "row_count": {
                    "type": "integer",
                    "description": "Number of rows"
                },
                "where_clause": {
                    "type": ["string", "null"],
                    "description": "Applied filter clause"
                },
                "timestamp": {
                    "type": "string",
                    "description": "ISO timestamp"
                }
            },
            "required": ["success", "source_name", "row_count"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute row counting"""
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
                'source_name': source_name,
                'row_count': count,
                'where_clause': where_clause if where_clause else None,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Failed to count rows in {source_name}: {str(e)}")
            return self._error_response(f"Failed to count rows: {str(e)}")


# Tool registry for easy access
SQLSELECT_TOOLS = {
    'sqlselect_list_sources': SqlSelectListSourcesTool,
    'sqlselect_describe_source': SqlSelectDescribeSourceTool,
    'sqlselect_execute_query': SqlSelectExecuteQueryTool,
    'sqlselect_sample_data': SqlSelectSampleDataTool,
    'sqlselect_get_schema': SqlSelectGetSchemaTool,
    'sqlselect_count_rows': SqlSelectCountRowsTool
}
