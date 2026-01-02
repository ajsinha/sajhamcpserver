"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
DuckDB OLAP Analytics MCP Tool Implementation - Refactored with Individual Tools
With Auto-Refresh Support
"""

import os
import json
import time
import threading
import atexit
from typing import Dict, Any, List, Optional
from datetime import datetime
from sajha.tools.base_mcp_tool import BaseMCPTool

try:
    import duckdb
except ImportError:
    raise ImportError("DuckDB is required. Install with: pip install duckdb --break-system-packages")


class DuckDbBaseTool(BaseMCPTool):
    """
    Base class for DuckDB tools with shared functionality
    """

    def __init__(self, config: Dict = None):
        """Initialize DuckDB base tool"""
        super().__init__(config)

        # Data directory for CSV, Parquet, JSON files
        self.data_directory = self.config.get('data_directory', '/home/ashutosh/PycharmProjects/sajhamcpserver/data/duckdb')

        # Auto-refresh configuration
        self.auto_refresh_enabled = self.config.get('auto_refresh_enabled', True)
        self.auto_refresh_interval = self.config.get('auto_refresh_interval', 600)  # Default: 10 minutes (600 seconds)

        # Ensure data directory exists
        os.makedirs(self.data_directory, exist_ok=True)

        # Initialize DuckDB connection
        self.db_path = os.path.join(self.data_directory, 'duckdb_analytics.db')
        self.conn = None

        # Track file states for change detection
        self._file_states = {}  # {filename: {'mtime': timestamp, 'size': bytes, 'view_name': str}}

        # Auto-refresh thread control
        self._refresh_thread = None
        self._stop_refresh = threading.Event()

        # Initialize views from data files
        self._initialize_views_from_files()

        # Start auto-refresh thread if enabled
        if self.auto_refresh_enabled:
            self._start_auto_refresh()
            # Register cleanup on exit
            atexit.register(self._stop_auto_refresh)

    def _get_connection(self):
        """Get or create DuckDB connection"""
        if self.conn is None:
            self.conn = duckdb.connect(self.db_path)
            # Enable automatic CSV/Parquet detection
            self.conn.execute("SET enable_object_cache=true")
        return self.conn

    def _execute_query(self, query: str) -> duckdb.DuckDBPyRelation:
        """
        Execute a query and return results

        Args:
            query: SQL query string

        Returns:
            Query results
        """
        conn = self._get_connection()
        try:
            result = conn.execute(query)
            return result
        except Exception as e:
            self.logger.error(f"Query execution failed: {e}")
            raise ValueError(f"Query failed: {str(e)}")

    def _format_file_size(self, size_bytes: int) -> str:
        """Format file size in human-readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"

    def _scan_data_files(self, file_type: str = 'all') -> List[Dict]:
        """Scan data directory for supported file types"""
        supported_extensions = {
            'csv': ['.csv'],
            'parquet': ['.parquet', '.pq'],
            'json': ['.json', '.jsonl'],
            'tsv': ['.tsv']
        }

        if file_type != 'all':
            extensions = supported_extensions.get(file_type, [])
        else:
            extensions = [ext for exts in supported_extensions.values() for ext in exts]

        files = []

        if os.path.exists(self.data_directory):
            for filename in os.listdir(self.data_directory):
                if filename.startswith('.') or filename.endswith('.db'):
                    continue

                file_ext = os.path.splitext(filename)[1].lower()
                if file_ext in extensions:
                    file_path = os.path.join(self.data_directory, filename)

                    # Determine file type
                    if file_ext in ['.csv']:
                        ftype = 'csv'
                    elif file_ext in ['.parquet', '.pq']:
                        ftype = 'parquet'
                    elif file_ext in ['.json', '.jsonl']:
                        ftype = 'json'
                    elif file_ext in ['.tsv']:
                        ftype = 'tsv'
                    else:
                        continue

                    file_info = {
                        'filename': filename,
                        'file_type': ftype,
                        'file_path': file_path
                    }

                    try:
                        stat = os.stat(file_path)
                        file_info['file_size_bytes'] = stat.st_size
                        file_info['file_size_human'] = self._format_file_size(stat.st_size)
                        file_info['modified_date'] = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    except:
                        pass

                    files.append(file_info)

        return files

    def _initialize_views_from_files(self):
        """
        Initialize views from all data files in the data directory.
        Creates a view for each CSV, Parquet, JSON, and TSV file found.
        """
        try:
            # Get connection
            conn = self._get_connection()

            # Scan for all data files
            files = self._scan_data_files()

            if not files:
                self.logger.info(f"No data files found in {self.data_directory}")
                return

            self.logger.info(f"Found {len(files)} data files in {self.data_directory}")

            # Create views for each file
            for file_info in files:
                try:
                    filename = file_info['filename']
                    file_path = file_info['file_path']
                    file_type = file_info['file_type']

                    # Generate view name from filename (remove extension and sanitize)
                    view_name = os.path.splitext(filename)[0]
                    # Replace special characters with underscores
                    view_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in view_name)

                    # Drop existing view if it exists
                    try:
                        conn.execute(f"DROP VIEW IF EXISTS {view_name}")
                    except:
                        pass

                    # Create view based on file type
                    if file_type == 'csv':
                        # DuckDB can read CSV files directly
                        create_view_sql = f"""
                            CREATE VIEW {view_name} AS 
                            SELECT * FROM read_csv_auto('{file_path}', 
                                header=true, 
                                auto_detect=true,
                                sample_size=-1
                            )
                        """
                    elif file_type == 'parquet':
                        # DuckDB can read Parquet files directly
                        create_view_sql = f"""
                            CREATE VIEW {view_name} AS 
                            SELECT * FROM read_parquet('{file_path}')
                        """
                    elif file_type == 'json':
                        # DuckDB can read JSON files directly
                        create_view_sql = f"""
                            CREATE VIEW {view_name} AS 
                            SELECT * FROM read_json_auto('{file_path}')
                        """
                    elif file_type == 'tsv':
                        # Read TSV as CSV with tab delimiter
                        create_view_sql = f"""
                            CREATE VIEW {view_name} AS 
                            SELECT * FROM read_csv_auto('{file_path}', 
                                header=true,
                                delim='\\t',
                                auto_detect=true,
                                sample_size=-1
                            )
                        """
                    else:
                        self.logger.warning(f"Unsupported file type '{file_type}' for {filename}")
                        continue

                    # Execute the CREATE VIEW statement
                    conn.execute(create_view_sql)

                    # Track file state for change detection
                    try:
                        stat = os.stat(file_path)
                        self._file_states[filename] = {
                            'mtime': stat.st_mtime,
                            'size': stat.st_size,
                            'view_name': view_name,
                            'file_type': file_type,
                            'file_path': file_path
                        }
                    except:
                        pass

                    # Get row count for verification
                    try:
                        row_count = conn.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()[0]
                        self.logger.info(f"✓ Created view '{view_name}' from {filename} ({row_count:,} rows)")
                    except Exception as e:
                        self.logger.info(f"✓ Created view '{view_name}' from {filename}")

                except Exception as e:
                    self.logger.error(f"Failed to create view for {filename}: {e}")
                    continue

            # Log summary
            views_result = conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_type = 'VIEW'").fetchone()
            total_views = views_result[0] if views_result else 0
            self.logger.info(f"Initialization complete: {total_views} views available")

        except Exception as e:
            self.logger.error(f"Failed to initialize views from files: {e}")
            # Don't raise - allow the tool to continue even if initialization fails

    def _start_auto_refresh(self):
        """Start the auto-refresh background thread"""
        if self._refresh_thread is None or not self._refresh_thread.is_alive():
            self._stop_refresh.clear()
            self._refresh_thread = threading.Thread(
                target=self._auto_refresh_worker,
                daemon=True,
                name="DuckDB-AutoRefresh"
            )
            self._refresh_thread.start()
            self.logger.info(f"Auto-refresh enabled: checking every {self.auto_refresh_interval} seconds")

    def _stop_auto_refresh(self):
        """Stop the auto-refresh background thread"""
        if self._refresh_thread and self._refresh_thread.is_alive():
            self._stop_refresh.set()
            self._refresh_thread.join(timeout=5)
            self.logger.info("Auto-refresh stopped")

    def _auto_refresh_worker(self):
        """Background worker that periodically checks for file changes"""
        while not self._stop_refresh.is_set():
            try:
                # Wait for the configured interval (but check every second for stop signal)
                for _ in range(self.auto_refresh_interval):
                    if self._stop_refresh.is_set():
                        return
                    time.sleep(1)

                # Perform the refresh check
                self._check_and_sync_views()

            except Exception as e:
                self.logger.error(f"Auto-refresh error: {e}")
                # Continue running despite errors

    def _check_and_sync_views(self):
        """
        Check for file changes and sync views accordingly:
        - Add views for new files
        - Remove views for deleted files
        - Reload views for modified files
        """
        try:
            conn = self._get_connection()

            # Scan current files in directory
            current_files = self._scan_data_files()
            current_filenames = {f['filename'] for f in current_files}
            current_file_map = {f['filename']: f for f in current_files}

            # Track what we tracked before
            tracked_filenames = set(self._file_states.keys())

            changes_made = False

            # 1. Detect and handle DELETED files
            deleted_files = tracked_filenames - current_filenames
            for filename in deleted_files:
                try:
                    view_name = self._file_states[filename]['view_name']
                    conn.execute(f"DROP VIEW IF EXISTS {view_name}")
                    del self._file_states[filename]
                    self.logger.info(f"🗑️  Removed view '{view_name}' (file deleted: {filename})")
                    changes_made = True
                except Exception as e:
                    self.logger.error(f"Failed to remove view for {filename}: {e}")

            # 2. Detect and handle NEW files
            new_files = current_filenames - tracked_filenames
            for filename in new_files:
                try:
                    file_info = current_file_map[filename]
                    file_path = file_info['file_path']
                    file_type = file_info['file_type']

                    # Generate view name
                    view_name = os.path.splitext(filename)[0]
                    view_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in view_name)

                    # Create view based on file type
                    if file_type == 'csv':
                        create_view_sql = f"""
                            CREATE VIEW {view_name} AS 
                            SELECT * FROM read_csv_auto('{file_path}', 
                                header=true, auto_detect=true, sample_size=-1)
                        """
                    elif file_type == 'parquet':
                        create_view_sql = f"""
                            CREATE VIEW {view_name} AS 
                            SELECT * FROM read_parquet('{file_path}')
                        """
                    elif file_type == 'json':
                        create_view_sql = f"""
                            CREATE VIEW {view_name} AS 
                            SELECT * FROM read_json_auto('{file_path}')
                        """
                    elif file_type == 'tsv':
                        create_view_sql = f"""
                            CREATE VIEW {view_name} AS 
                            SELECT * FROM read_csv_auto('{file_path}', 
                                header=true, delim='\\t', auto_detect=true, sample_size=-1)
                        """
                    else:
                        continue

                    # Create the view
                    conn.execute(create_view_sql)

                    # Track the new file
                    stat = os.stat(file_path)
                    self._file_states[filename] = {
                        'mtime': stat.st_mtime,
                        'size': stat.st_size,
                        'view_name': view_name,
                        'file_type': file_type,
                        'file_path': file_path
                    }

                    self.logger.info(f"➕ Created view '{view_name}' (new file: {filename})")
                    changes_made = True

                except Exception as e:
                    self.logger.error(f"Failed to create view for new file {filename}: {e}")

            # 3. Detect and handle MODIFIED files
            existing_files = current_filenames & tracked_filenames
            for filename in existing_files:
                try:
                    file_info = current_file_map[filename]
                    file_path = file_info['file_path']

                    # Check if file was modified
                    stat = os.stat(file_path)
                    old_state = self._file_states[filename]

                    if stat.st_mtime != old_state['mtime'] or stat.st_size != old_state['size']:
                        # File was modified - reload the view
                        view_name = old_state['view_name']
                        file_type = old_state['file_type']

                        # Drop and recreate the view
                        conn.execute(f"DROP VIEW IF EXISTS {view_name}")

                        if file_type == 'csv':
                            create_view_sql = f"""
                                CREATE VIEW {view_name} AS 
                                SELECT * FROM read_csv_auto('{file_path}', 
                                    header=true, auto_detect=true, sample_size=-1)
                            """
                        elif file_type == 'parquet':
                            create_view_sql = f"""
                                CREATE VIEW {view_name} AS 
                                SELECT * FROM read_parquet('{file_path}')
                            """
                        elif file_type == 'json':
                            create_view_sql = f"""
                                CREATE VIEW {view_name} AS 
                                SELECT * FROM read_json_auto('{file_path}')
                            """
                        elif file_type == 'tsv':
                            create_view_sql = f"""
                                CREATE VIEW {view_name} AS 
                                SELECT * FROM read_csv_auto('{file_path}', 
                                    header=true, delim='\\t', auto_detect=true, sample_size=-1)
                            """
                        else:
                            continue

                        conn.execute(create_view_sql)

                        # Update tracked state
                        self._file_states[filename]['mtime'] = stat.st_mtime
                        self._file_states[filename]['size'] = stat.st_size

                        self.logger.info(f"🔄 Reloaded view '{view_name}' (file modified: {filename})")
                        changes_made = True

                except Exception as e:
                    self.logger.error(f"Failed to reload view for modified file {filename}: {e}")

            # Log summary if changes were made
            if changes_made:
                views_result = conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_type = 'VIEW'").fetchone()
                total_views = views_result[0] if views_result else 0
                self.logger.info(f"Auto-refresh complete: {total_views} views available")

        except Exception as e:
            self.logger.error(f"Failed to check and sync views: {e}")

    def close(self):
        """Close DuckDB connection and stop auto-refresh"""
        # Stop auto-refresh thread
        self._stop_auto_refresh()

        # Close connection
        if self.conn:
            self.conn.close()
            self.conn = None


class DuckDbListTablesTool(DuckDbBaseTool):
    """
    Tool to list all available tables and views
    """

    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'duckdb_list_tables',
            'description': 'List all available tables and views in the DuckDB database',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute list tables operation"""
        include_system = arguments.get('include_system_tables', False)

        try:
            conn = self._get_connection()

            # Get all tables and views
            query = """
                SELECT 
                    table_name as name,
                    table_type as type,
                    'main' as schema
                FROM information_schema.tables
            """

            if not include_system:
                query += " WHERE table_schema = 'main'"

            result = conn.execute(query).fetchall()

            tables = []
            for row in result:
                table_info = {
                    'name': row[0],
                    'type': 'view' if row[1].lower() == 'view' else 'table',
                    'schema': row[2]
                }

                # Try to get row count
                try:
                    count_query = f"SELECT COUNT(*) FROM {row[0]}"
                    count_result = conn.execute(count_query).fetchone()
                    table_info['row_count'] = count_result[0] if count_result else 0
                except:
                    table_info['row_count'] = None

                tables.append(table_info)

            return {
                'tables': tables,
                'total_count': len(tables)
            }

        except Exception as e:
            self.logger.error(f"Failed to list tables: {e}")
            raise


class DuckDbDescribeTableTool(DuckDbBaseTool):
    """
    Tool to describe table schema and structure
    """

    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'duckdb_describe_table',
            'description': 'Get detailed schema information for a specific table or view',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute describe table operation"""
        table_name = arguments['table_name']
        include_sample = arguments.get('include_sample_data', False)
        sample_size = arguments.get('sample_size', 5)

        try:
            conn = self._get_connection()

            # Get table type
            table_type_query = f"""
                SELECT table_type 
                FROM information_schema.tables 
                WHERE table_name = '{table_name}'
            """
            table_type_result = conn.execute(table_type_query).fetchone()
            table_type = 'view' if table_type_result and table_type_result[0].lower() == 'view' else 'table'

            # Get column information
            describe_query = f"DESCRIBE {table_name}"
            describe_result = conn.execute(describe_query).fetchall()

            columns = []
            for row in describe_result:
                column_info = {
                    'column_name': row[0],
                    'data_type': row[1],
                    'nullable': row[2] == 'YES' if len(row) > 2 else True,
                    'is_primary_key': False
                }

                if len(row) > 3 and row[3]:
                    column_info['default_value'] = str(row[3])

                columns.append(column_info)

            # Get row count
            count_query = f"SELECT COUNT(*) FROM {table_name}"
            row_count = conn.execute(count_query).fetchone()[0]

            result = {
                'table_name': table_name,
                'table_type': table_type,
                'columns': columns,
                'row_count': row_count
            }

            # Get sample data if requested
            if include_sample:
                sample_query = f"SELECT * FROM {table_name} LIMIT {sample_size}"
                sample_result = conn.execute(sample_query).fetchdf()
                result['sample_data'] = sample_result.to_dict(orient='records')

            return result

        except Exception as e:
            self.logger.error(f"Failed to describe table: {e}")
            raise


class DuckDbQueryTool(DuckDbBaseTool):
    """
    Tool to execute SQL queries
    """

    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'duckdb_query',
            'description': 'Execute SQL queries on data files using DuckDB',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute SQL query"""
        sql_query = arguments['sql_query']
        limit = arguments.get('limit', 100)
        output_format = arguments.get('output_format', 'json')

        # Prevent destructive operations
        forbidden_keywords = ['DROP', 'DELETE', 'TRUNCATE', 'ALTER', 'CREATE', 'INSERT', 'UPDATE']
        query_upper = sql_query.upper()
        for keyword in forbidden_keywords:
            if keyword in query_upper:
                raise ValueError(f"Forbidden operation: {keyword}. Only read-only queries are allowed.")

        try:
            start_time = time.time()

            # Add LIMIT if not already present
            if 'LIMIT' not in query_upper:
                sql_query = f"{sql_query.rstrip(';')} LIMIT {limit}"

            conn = self._get_connection()
            result = conn.execute(sql_query)

            # Get results as DataFrame for easier manipulation
            df = result.fetchdf()

            execution_time = (time.time() - start_time) * 1000  # Convert to ms

            response = {
                'query': sql_query,
                'columns': list(df.columns),
                'rows': df.to_dict(orient='records'),
                'row_count': len(df),
                'execution_time_ms': round(execution_time, 2),
                'limited': len(df) >= limit
            }

            return response

        except Exception as e:
            self.logger.error(f"Failed to execute query: {e}")
            raise


class DuckDbRefreshViewsTool(DuckDbBaseTool):
    """
    Tool to refresh materialized views
    """

    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'duckdb_refresh_views',
            'description': 'Refresh materialized views or reload external data files',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute refresh views operation"""
        view_name = arguments.get('view_name')
        reload_external = arguments.get('reload_external_files', False)

        try:
            conn = self._get_connection()
            refreshed_views = []

            # Reload external files if requested
            if reload_external:
                self.logger.info("Reloading external data files...")
                self._initialize_views_from_files()

            # Get list of views to refresh
            if view_name:
                views = [view_name]
            else:
                views_query = """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_type = 'VIEW'
                """
                views = [row[0] for row in conn.execute(views_query).fetchall()]

            # Refresh each view
            for view in views:
                try:
                    start_time = time.time()

                    # For standard views, just query to validate
                    count_result = conn.execute(f"SELECT COUNT(*) FROM {view}").fetchone()
                    row_count = count_result[0] if count_result else 0

                    refresh_time = (time.time() - start_time) * 1000

                    refreshed_views.append({
                        'view_name': view,
                        'status': 'success',
                        'row_count': row_count,
                        'refresh_time_ms': round(refresh_time, 2)
                    })

                except Exception as e:
                    refreshed_views.append({
                        'view_name': view,
                        'status': 'failed',
                        'error_message': str(e)
                    })

            return {
                'refreshed_views': refreshed_views,
                'total_refreshed': len([v for v in refreshed_views if v['status'] == 'success']),
                'external_files_reloaded': reload_external
            }

        except Exception as e:
            self.logger.error(f"Failed to refresh views: {e}")
            raise


class DuckDbGetStatsTool(DuckDbBaseTool):
    """
    Tool to get statistical summary for table columns
    """

    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'duckdb_get_stats',
            'description': 'Get statistical summary for numeric columns in a table',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute get stats operation"""
        table_name = arguments['table_name']
        columns = arguments.get('columns', [])
        include_percentiles = arguments.get('include_percentiles', True)

        try:
            conn = self._get_connection()

            # Get all columns if not specified
            if not columns:
                describe_result = conn.execute(f"DESCRIBE {table_name}").fetchall()
                all_columns = [row[0] for row in describe_result]
            else:
                all_columns = columns

            # Get total row count
            total_rows = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

            column_statistics = {}

            for col in all_columns:
                try:
                    # Build statistics query
                    stats_parts = [
                        f"COUNT({col}) as count",
                        f"COUNT(*) - COUNT({col}) as null_count",
                        f"MIN({col}) as min",
                        f"MAX({col}) as max",
                        f"COUNT(DISTINCT {col}) as unique_count"
                    ]

                    # Try numeric statistics
                    try:
                        numeric_stats = [
                            f"AVG({col}) as mean",
                            f"STDDEV({col}) as std_dev"
                        ]

                        if include_percentiles:
                            numeric_stats.extend([
                                f"PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {col}) as percentile_25",
                                f"PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY {col}) as median",
                                f"PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {col}) as percentile_75"
                            ])

                        stats_query = f"SELECT {', '.join(stats_parts + numeric_stats)} FROM {table_name}"
                        stats = conn.execute(stats_query).fetchone()

                        column_statistics[col] = {
                            'count': stats[0],
                            'null_count': stats[1],
                            'min': stats[2],
                            'max': stats[3],
                            'unique_count': stats[4],
                            'mean': float(stats[5]) if stats[5] is not None else None,
                            'std_dev': float(stats[6]) if stats[6] is not None else None,
                            'data_type': 'numeric'
                        }

                        if include_percentiles:
                            column_statistics[col].update({
                                'percentile_25': float(stats[7]) if stats[7] is not None else None,
                                'median': float(stats[8]) if stats[8] is not None else None,
                                'percentile_75': float(stats[9]) if stats[9] is not None else None
                            })

                    except:
                        # Non-numeric column
                        stats_query = f"SELECT {', '.join(stats_parts)} FROM {table_name}"
                        stats = conn.execute(stats_query).fetchone()

                        column_statistics[col] = {
                            'count': stats[0],
                            'null_count': stats[1],
                            'min': stats[2],
                            'max': stats[3],
                            'unique_count': stats[4],
                            'data_type': 'non-numeric'
                        }

                except Exception as e:
                    self.logger.warning(f"Failed to get stats for column {col}: {e}")
                    continue

            return {
                'table_name': table_name,
                'total_rows': total_rows,
                'column_statistics': column_statistics
            }

        except Exception as e:
            self.logger.error(f"Failed to get statistics: {e}")
            raise


class DuckDbAggregateTool(DuckDbBaseTool):
    """
    Tool to perform aggregation operations
    """

    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'duckdb_aggregate',
            'description': 'Perform aggregation operations with grouping',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute aggregation operation"""
        table_name = arguments['table_name']
        aggregations = arguments['aggregations']
        group_by = arguments.get('group_by', [])
        having = arguments.get('having')
        order_by = arguments.get('order_by', [])
        limit = arguments.get('limit', 100)

        try:
            start_time = time.time()

            # Build aggregation expressions
            agg_expressions = []
            for col, func in aggregations.items():
                func_upper = func.upper()
                if func_upper in ['SUM', 'AVG', 'COUNT', 'MIN', 'MAX']:
                    agg_expressions.append(f"{func_upper}({col}) as {func}_{col}")
                elif func_upper == 'COUNT_DISTINCT':
                    agg_expressions.append(f"COUNT(DISTINCT {col}) as count_distinct_{col}")

            # Build SELECT clause
            if group_by:
                select_clause = f"SELECT {', '.join(group_by)}, {', '.join(agg_expressions)}"
            else:
                select_clause = f"SELECT {', '.join(agg_expressions)}"

            # Build query
            query = f"{select_clause} FROM {table_name}"

            if group_by:
                query += f" GROUP BY {', '.join(group_by)}"

            if having:
                query += f" HAVING {having}"

            if order_by:
                order_clauses = []
                for order in order_by:
                    col = order.get('column')
                    direction = order.get('direction', 'asc').upper()
                    order_clauses.append(f"{col} {direction}")
                query += f" ORDER BY {', '.join(order_clauses)}"

            query += f" LIMIT {limit}"

            conn = self._get_connection()
            result = conn.execute(query)
            df = result.fetchdf()

            execution_time = (time.time() - start_time) * 1000

            return {
                'table_name': table_name,
                'aggregations_applied': aggregations,
                'grouped_by': group_by,
                'results': df.to_dict(orient='records'),
                'row_count': len(df),
                'execution_time_ms': round(execution_time, 2)
            }

        except Exception as e:
            self.logger.error(f"Failed to perform aggregation: {e}")
            raise


class DuckDbListFilesTool(DuckDbBaseTool):
    """
    Tool to list available data files
    """

    def __init__(self, config: Dict = None):
        default_config = {
            'name': 'duckdb_list_files',
            'description': 'List available data files in the data directory',
            'version': '1.0.0',
            'enabled': True
        }
        if config:
            default_config.update(config)
        super().__init__(default_config)

    def get_input_schema(self) -> Dict:
        return self.config.get('inputSchema', {})

    def get_output_schema(self) -> Dict:
        return self.config.get('outputSchema', {})

    def execute(self, arguments: Dict[str, Any]) -> Dict:
        """Execute list files operation"""
        file_type = arguments.get('file_type', 'all')
        include_metadata = arguments.get('include_metadata', True)

        try:
            files = self._scan_data_files(file_type)

            # Calculate summary
            summary = {
                'csv_count': len([f for f in files if f['file_type'] == 'csv']),
                'parquet_count': len([f for f in files if f['file_type'] == 'parquet']),
                'json_count': len([f for f in files if f['file_type'] == 'json']),
                'tsv_count': len([f for f in files if f['file_type'] == 'tsv']),
                'total_size_bytes': sum(f.get('file_size_bytes', 0) for f in files)
            }

            # Check which files are loaded
            try:
                conn = self._get_connection()
                tables_result = conn.execute("SELECT table_name FROM information_schema.tables").fetchall()
                loaded_tables = [row[0] for row in tables_result]

                for file_info in files:
                    table_name = os.path.splitext(file_info['filename'])[0]
                    file_info['is_loaded'] = table_name in loaded_tables
                    if file_info['is_loaded']:
                        file_info['table_name'] = table_name
            except:
                pass

            return {
                'data_directory': self.data_directory,
                'files': files,
                'total_files': len(files),
                'summary': summary
            }

        except Exception as e:
            self.logger.error(f"Failed to list files: {e}")
            raise


# Tool registry for easy access
DUCKDB_TOOLS = {
    'duckdb_list_tables': DuckDbListTablesTool,
    'duckdb_describe_table': DuckDbDescribeTableTool,
    'duckdb_query': DuckDbQueryTool,
    'duckdb_refresh_views': DuckDbRefreshViewsTool,
    'duckdb_get_stats': DuckDbGetStatsTool,
    'duckdb_aggregate': DuckDbAggregateTool,
    'duckdb_list_files': DuckDbListFilesTool
}