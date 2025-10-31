"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
DuckDB OLAP Tools - MCP Tool Implementation
"""

import json
import os
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime
from ..base_mcp_tool import BaseMCPTool


class DuckDbOlapToolsTool(BaseMCPTool):
    """
    DuckDB OLAP tool for analyzing CSV, Parquet, and JSON files
    
    Features:
    - Automatic file detection and view creation
    - SQL query execution
    - OLAP operations
    - Data statistics and aggregations
    """
    
    def __init__(self, config: Dict = None):
        """Initialize DuckDB OLAP Tools"""
        default_config = {
            'name': 'duckdb_olap_tools',
            'description': 'DuckDB OLAP analytics for CSV, Parquet, and JSON files',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)
        
        # Data directory
        self.data_dir = config.get('data_directory', 'data/duckdb') if config else 'data/duckdb'
        
        # Ensure directory exists
        os.makedirs(self.data_dir, exist_ok=True)
        
        # Track file states
        self.file_registry = {}
        self.db_connection = None
        
        # Initialize DuckDB
        self._init_duckdb()
    
    def _init_duckdb(self):
        """Initialize DuckDB connection"""
        try:
            import duckdb
            # Create in-memory database
            self.db_connection = duckdb.connect(':memory:')
            self.logger.info("DuckDB initialized successfully")
            
            # Initial scan
            self._scan_and_register_files()
        except ImportError:
            self.logger.warning("DuckDB not available - install with: pip install duckdb")
            self.db_connection = None
    
    def _scan_and_register_files(self):
        """Scan directory and register files as views"""
        if not self.db_connection:
            return
        
        path = Path(self.data_dir)
        current_files = {}
        
        # Supported extensions
        extensions = ['.csv', '.parquet', '.json']
        
        for ext in extensions:
            for file_path in path.glob(f'*{ext}'):
                if file_path.is_file():
                    file_name = file_path.name
                    file_stat = file_path.stat()
                    file_key = str(file_path)
                    
                    current_files[file_key] = {
                        'name': file_name,
                        'path': str(file_path),
                        'extension': ext,
                        'size': file_stat.st_size,
                        'modified': file_stat.st_mtime
                    }
        
        # Find new files
        new_files = set(current_files.keys()) - set(self.file_registry.keys())
        
        # Find removed files
        removed_files = set(self.file_registry.keys()) - set(current_files.keys())
        
        # Register new files
        for file_key in new_files:
            self._register_file(current_files[file_key])
        
        # Unregister removed files
        for file_key in removed_files:
            self._unregister_file(self.file_registry[file_key])
        
        # Update registry
        self.file_registry = current_files
        
        self.logger.info(f"Registered {len(self.file_registry)} files as views")
    
    def _register_file(self, file_info: Dict):
        """Register a file as a DuckDB view"""
        try:
            view_name = self._get_view_name(file_info['name'])
            file_path = file_info['path']
            extension = file_info['extension']
            
            # Create view based on file type
            if extension == '.csv':
                query = f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM read_csv_auto('{file_path}')"
            elif extension == '.parquet':
                query = f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM read_parquet('{file_path}')"
            elif extension == '.json':
                query = f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM read_json_auto('{file_path}')"
            else:
                return
            
            self.db_connection.execute(query)
            self.logger.info(f"Registered view: {view_name} from {file_info['name']}")
            
        except Exception as e:
            self.logger.error(f"Error registering file {file_info['name']}: {e}")
    
    def _unregister_file(self, file_info: Dict):
        """Unregister a file view"""
        try:
            view_name = self._get_view_name(file_info['name'])
            self.db_connection.execute(f"DROP VIEW IF EXISTS {view_name}")
            self.logger.info(f"Unregistered view: {view_name}")
        except Exception as e:
            self.logger.error(f"Error unregistering file {file_info['name']}: {e}")
    
    def _get_view_name(self, filename: str) -> str:
        """Convert filename to valid view name"""
        # Remove extension and sanitize
        name = Path(filename).stem
        # Replace non-alphanumeric with underscore
        name = ''.join(c if c.isalnum() else '_' for c in name)
        return name.lower()
    
    def get_input_schema(self) -> Dict:
        """Get input schema for DuckDB OLAP Tools"""
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": [
                        "list_tables",
                        "describe_table",
                        "query",
                        "refresh_views",
                        "get_stats",
                        "aggregate",
                        "list_files"
                    ]
                },
                "table_name": {
                    "type": "string",
                    "description": "Name of table/view"
                },
                "sql_query": {
                    "type": "string",
                    "description": "SQL query to execute"
                },
                "columns": {
                    "type": "array",
                    "description": "Columns for aggregation",
                    "items": {"type": "string"}
                },
                "group_by": {
                    "type": "array",
                    "description": "Columns to group by",
                    "items": {"type": "string"}
                },
                "aggregations": {
                    "type": "object",
                    "description": "Aggregation functions (e.g., {'col': 'sum'})"
                },
                "limit": {
                    "type": "integer",
                    "description": "Limit number of results",
                    "default": 100,
                    "minimum": 1,
                    "maximum": 10000
                }
            },
            "required": ["action"]
        }
    
    def execute(self, arguments: Dict[str, Any]) -> Any:
        """
        Execute DuckDB OLAP Tools action
        
        Args:
            arguments: Tool arguments
            
        Returns:
            Result based on action
        """
        if not self.db_connection:
            return {
                'error': 'DuckDB not available',
                'note': 'Install DuckDB: pip install duckdb'
            }
        
        action = arguments.get('action')
        
        if action == 'list_tables':
            return self._list_tables()
            
        elif action == 'describe_table':
            table_name = arguments.get('table_name')
            if not table_name:
                raise ValueError("'table_name' is required")
            return self._describe_table(table_name)
            
        elif action == 'query':
            sql_query = arguments.get('sql_query')
            if not sql_query:
                raise ValueError("'sql_query' is required")
            limit = arguments.get('limit', 100)
            return self._execute_query(sql_query, limit)
            
        elif action == 'refresh_views':
            return self._refresh_views()
            
        elif action == 'get_stats':
            table_name = arguments.get('table_name')
            if not table_name:
                raise ValueError("'table_name' is required")
            return self._get_table_stats(table_name)
            
        elif action == 'aggregate':
            table_name = arguments.get('table_name')
            aggregations = arguments.get('aggregations', {})
            group_by = arguments.get('group_by', [])
            if not table_name:
                raise ValueError("'table_name' is required")
            return self._aggregate(table_name, aggregations, group_by)
            
        elif action == 'list_files':
            return self._list_files()
            
        else:
            raise ValueError(f"Unknown action: {action}")
    
    def _list_tables(self) -> Dict:
        """List all available tables/views"""
        try:
            # Refresh file registry
            self._scan_and_register_files()
            
            result = self.db_connection.execute("SHOW TABLES").fetchall()
            
            tables = []
            for row in result:
                table_name = row[0]
                
                # Get row count
                try:
                    count_result = self.db_connection.execute(
                        f"SELECT COUNT(*) FROM {table_name}"
                    ).fetchone()
                    row_count = count_result[0] if count_result else 0
                except:
                    row_count = None
                
                tables.append({
                    'name': table_name,
                    'row_count': row_count
                })
            
            return {
                'table_count': len(tables),
                'tables': tables,
                'data_directory': self.data_dir
            }
            
        except Exception as e:
            self.logger.error(f"Error listing tables: {e}")
            raise ValueError(f"Failed to list tables: {str(e)}")
    
    def _describe_table(self, table_name: str) -> Dict:
        """Describe table schema"""
        try:
            result = self.db_connection.execute(f"DESCRIBE {table_name}").fetchall()
            
            columns = []
            for row in result:
                columns.append({
                    'name': row[0],
                    'type': row[1],
                    'null': row[2] if len(row) > 2 else None
                })
            
            # Get sample data
            sample_result = self.db_connection.execute(
                f"SELECT * FROM {table_name} LIMIT 5"
            ).fetchall()
            
            return {
                'table_name': table_name,
                'columns': columns,
                'column_count': len(columns),
                'sample_data': sample_result
            }
            
        except Exception as e:
            self.logger.error(f"Error describing table: {e}")
            raise ValueError(f"Failed to describe table: {str(e)}")
    
    def _execute_query(self, sql_query: str, limit: int = 100) -> Dict:
        """Execute SQL query"""
        try:
            # Add limit if not present
            query = sql_query.strip()
            if 'LIMIT' not in query.upper():
                query += f" LIMIT {limit}"
            
            result = self.db_connection.execute(query)
            
            # Get column names
            columns = [desc[0] for desc in result.description]
            
            # Fetch data
            rows = result.fetchall()
            
            return {
                'query': sql_query,
                'columns': columns,
                'row_count': len(rows),
                'rows': rows,
                'limited': True if 'LIMIT' not in sql_query.upper() else False
            }
            
        except Exception as e:
            self.logger.error(f"Error executing query: {e}")
            raise ValueError(f"Query failed: {str(e)}")
    
    def _refresh_views(self) -> Dict:
        """Refresh file views"""
        try:
            old_count = len(self.file_registry)
            self._scan_and_register_files()
            new_count = len(self.file_registry)
            
            return {
                'status': 'success',
                'previous_files': old_count,
                'current_files': new_count,
                'files_added': max(0, new_count - old_count),
                'files_removed': max(0, old_count - new_count),
                'data_directory': self.data_dir
            }
            
        except Exception as e:
            self.logger.error(f"Error refreshing views: {e}")
            raise ValueError(f"Failed to refresh views: {str(e)}")
    
    def _get_table_stats(self, table_name: str) -> Dict:
        """Get table statistics"""
        try:
            # Get column info
            desc_result = self.db_connection.execute(
                f"DESCRIBE {table_name}"
            ).fetchall()
            
            columns = [row[0] for row in desc_result]
            
            # Get row count
            count_result = self.db_connection.execute(
                f"SELECT COUNT(*) FROM {table_name}"
            ).fetchone()
            row_count = count_result[0]
            
            # Get stats for numeric columns
            numeric_stats = {}
            for col in columns:
                try:
                    stats_query = f"""
                        SELECT 
                            MIN({col}) as min_val,
                            MAX({col}) as max_val,
                            AVG({col}) as avg_val,
                            COUNT(DISTINCT {col}) as distinct_count
                        FROM {table_name}
                    """
                    stats_result = self.db_connection.execute(stats_query).fetchone()
                    
                    numeric_stats[col] = {
                        'min': stats_result[0],
                        'max': stats_result[1],
                        'avg': stats_result[2],
                        'distinct': stats_result[3]
                    }
                except:
                    # Column might not be numeric
                    try:
                        distinct_query = f"SELECT COUNT(DISTINCT {col}) FROM {table_name}"
                        distinct_result = self.db_connection.execute(distinct_query).fetchone()
                        numeric_stats[col] = {
                            'distinct': distinct_result[0]
                        }
                    except:
                        pass
            
            return {
                'table_name': table_name,
                'row_count': row_count,
                'column_count': len(columns),
                'columns': columns,
                'statistics': numeric_stats
            }
            
        except Exception as e:
            self.logger.error(f"Error getting stats: {e}")
            raise ValueError(f"Failed to get statistics: {str(e)}")
    
    def _aggregate(
        self,
        table_name: str,
        aggregations: Dict,
        group_by: List[str]
    ) -> Dict:
        """Perform aggregations"""
        try:
            # Build aggregation query
            agg_parts = []
            for col, func in aggregations.items():
                agg_parts.append(f"{func.upper()}({col}) as {col}_{func}")
            
            if not agg_parts:
                # Default: count all
                agg_parts = ["COUNT(*) as count"]
            
            # Build group by clause
            group_clause = ""
            select_parts = []
            if group_by:
                select_parts = group_by.copy()
                group_clause = f"GROUP BY {', '.join(group_by)}"
            
            # Build full query
            select_clause = ', '.join(select_parts + agg_parts)
            query = f"SELECT {select_clause} FROM {table_name} {group_clause}"
            
            result = self.db_connection.execute(query)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            
            return {
                'table_name': table_name,
                'query': query,
                'columns': columns,
                'row_count': len(rows),
                'rows': rows
            }
            
        except Exception as e:
            self.logger.error(f"Error in aggregation: {e}")
            raise ValueError(f"Aggregation failed: {str(e)}")
    
    def _list_files(self) -> Dict:
        """List files in data directory"""
        path = Path(self.data_dir)
        files = []
        
        extensions = ['.csv', '.parquet', '.json']
        
        for ext in extensions:
            for file_path in path.glob(f'*{ext}'):
                if file_path.is_file():
                    stat = file_path.stat()
                    view_name = self._get_view_name(file_path.name)
                    
                    files.append({
                        'filename': file_path.name,
                        'view_name': view_name,
                        'extension': ext,
                        'size': stat.st_size,
                        'size_mb': round(stat.st_size / (1024 * 1024), 2),
                        'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                    })
        
        files.sort(key=lambda x: x['modified'], reverse=True)
        
        return {
            'directory': self.data_dir,
            'file_count': len(files),
            'files': files
        }
