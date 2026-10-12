"""
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
DuckDB OLAP Analytics MCP Tool Implementation - Refactored with Individual Tools
With Auto-Refresh Support

Sandbox: the data files are copied into tables of an in-memory DuckDB (one per data
directory, shared by every ``duckdb_*`` tool), and then ``enable_external_access`` is
switched off and the configuration locked, so no query can read or write a file or URL
(``read_text``, ``read_csv``, ``read_parquet``, ``COPY``, ``ATTACH``, ``INSTALL``) or
turn that back on. A reload builds a new sandbox and swaps it in. Caller-supplied table
and column names are looked up in the catalog and used quoted; values are bound;
``duckdb_query`` runs exactly one read-only statement (``sajha/olap/sql_safety.py``).

Data on the storage backend: a data directory written ``storage://<prefix>`` (for example
``data.duckdb.dir: storage://data/duckdb``) is read through ``get_storage()`` (local, S3, Azure
Blob or GCS) instead of the local disk. At each (re)load every data file directly under the
prefix is staged into a temporary local directory (``data.duckdb.stage_dir``), copied into its
table, and the staged copy deleted; a file over ``data.duckdb.stage_max_file_mb``, or past
``data.duckdb.stage_max_total_mb`` for one load, is skipped and logged. Change detection uses
the objects' modified times, and a bucket event notification under the prefix
(sajha/core/storage_events.py) reloads the sandbox at once.
"""

import os
import re
import time
import logging
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime
from sajha.tools.base_mcp_tool import BaseMCPTool
from sajha.olap import sql_safety as sq

try:
    import duckdb
except ImportError:
    raise ImportError("DuckDB is required. Install with: pip install duckdb --break-system-packages")

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {
    'csv': ['.csv'],
    'parquet': ['.parquet', '.pq'],
    'json': ['.json', '.jsonl'],
    'tsv': ['.tsv'],
}
# file type -> loader; the path is always a bound parameter, never SQL text
_LOADERS = {
    'csv': "read_csv_auto(?, header=true, sample_size=-1)",
    'tsv': "read_csv_auto(?, header=true, delim='\t', sample_size=-1)",
    'parquet': "read_parquet(?)",
    'json': "read_json_auto(?)",
}
_HAVING_CONDITION = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|<>|!=|=|>|<)\s*"
    r"(-?\d+(?:\.\d+)?|'(?:[^']|'')*')\s*$")
_AGGREGATES = {
    'SUM': 'SUM({c})', 'AVG': 'AVG({c})', 'COUNT': 'COUNT({c})', 'MIN': 'MIN({c})',
    'MAX': 'MAX({c})', 'COUNT_DISTINCT': 'COUNT(DISTINCT {c})',
}


def _format_file_size(size_bytes: float) -> str:
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def _records(result, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Rows of a DuckDB result as dicts (no pandas/numpy needed)."""
    columns = [d[0] for d in result.description] if result.description else []
    rows = result.fetchall() if limit is None else result.fetchmany(limit)
    return [dict(zip(columns, r)) for r in rows]


def _table_name_for(filename: str) -> str:
    stem = os.path.splitext(filename)[0]
    return ''.join(c if c.isalnum() or c == '_' else '_' for c in stem)


STORAGE_SCHEME = 'storage://'


def storage_prefix(data_directory: str) -> Optional[str]:
    """The storage-backend prefix of a ``storage://<prefix>`` data directory, else None."""
    d = str(data_directory or '')
    if not d.startswith(STORAGE_SCHEME):
        return None
    prefix = d[len(STORAGE_SCHEME):].strip('/')
    if not prefix or '..' in prefix.split('/'):
        raise ValueError(f'{data_directory!r}: give a folder on the storage backend, without ".."')
    return prefix


def _extensions(file_type: str) -> List[str]:
    if file_type != 'all':
        return _SUPPORTED_EXTENSIONS.get(file_type, [])
    return [ext for exts in _SUPPORTED_EXTENSIONS.values() for ext in exts]


def _wanted(filename: str, extensions: List[str]) -> Optional[str]:
    if filename.startswith('.') or filename.endswith('.db'):
        return None
    ext = os.path.splitext(filename)[1].lower()
    if ext not in extensions:
        return None
    return next(t for t, exts in _SUPPORTED_EXTENSIONS.items() if ext in exts)


def _scan_storage(prefix: str, file_type: str) -> List[Dict]:
    """Data files directly under ``prefix`` on the storage backend (``file_path`` is the
    storage path; the size is known only once a load stages the file)."""
    from sajha.core.storage import get_storage
    backend = get_storage()
    extensions = _extensions(file_type)
    files = []
    base = prefix + '/'
    for path in backend.list_files(prefix, '*'):
        rest = path[len(base):] if path.startswith(base) else None
        if not rest or '/' in rest:
            continue
        ftype = _wanted(rest, extensions)
        if not ftype:
            continue
        info = {'filename': rest, 'file_type': ftype, 'file_path': path, 'source': 'storage'}
        try:
            info['modified_date'] = datetime.fromtimestamp(float(backend.get_modified_time(path))).isoformat()
        except Exception:
            pass
        files.append(info)
    return sorted(files, key=lambda f: f['filename'])


def scan_data_files(data_directory: str, file_type: str = 'all') -> List[Dict]:
    """The supported data files directly inside ``data_directory`` (a local directory, or
    ``storage://<prefix>`` on the storage backend)."""
    prefix = storage_prefix(data_directory)
    if prefix is not None:
        return _scan_storage(prefix, file_type)
    extensions = _extensions(file_type)
    files = []
    if not os.path.isdir(data_directory):
        return files
    for filename in sorted(os.listdir(data_directory)):
        ftype = _wanted(filename, extensions)
        if not ftype:
            continue
        path = os.path.join(data_directory, filename)
        if not os.path.isfile(path):
            continue
        info = {'filename': filename, 'file_type': ftype, 'file_path': path}
        try:
            stat = os.stat(path)
            info['file_size_bytes'] = stat.st_size
            info['file_size_human'] = _format_file_size(stat.st_size)
            info['modified_date'] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        except OSError as e:
            logger.warning(f"Cannot stat {path}: {e}")
        files.append(info)
    return files


def _stage_limits() -> tuple:
    from sajha.core.config import _get

    def mb(key, default):
        try:
            return max(0.0, float(_get(key, default) or default)) * 1024 * 1024
        except (TypeError, ValueError):
            return float(default) * 1024 * 1024
    return (mb('data.duckdb.stage_max_file_mb', 256), mb('data.duckdb.stage_max_total_mb', 1024),
            str(_get('data.duckdb.stage_dir', '') or '') or None)


class DuckDbSandbox:
    """One locked-down in-memory DuckDB per data directory, shared by the duckdb_* tools."""

    _instances: Dict[str, 'DuckDbSandbox'] = {}
    _instances_lock = threading.Lock()

    @classmethod
    def for_directory(cls, data_directory: str) -> 'DuckDbSandbox':
        key = data_directory if storage_prefix(data_directory) is not None else os.path.realpath(data_directory)
        with cls._instances_lock:
            box = cls._instances.get(key)
            if box is None:
                box = cls._instances[key] = cls(data_directory)
            return box

    def __init__(self, data_directory: str):
        self.data_directory = data_directory
        self._lock = threading.RLock()
        self._conn = None
        self.file_states: Dict[str, Dict[str, Any]] = {}
        self._refresh_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.prefix = storage_prefix(data_directory)
        self.reload()
        if self.prefix is not None:
            try:
                from sajha.core.storage_events import add_path_listener
                add_path_listener(self._on_storage_paths)
            except Exception as e:
                logger.debug(f'DuckDB: storage events unavailable: {e}')

    def _on_storage_paths(self, paths: List[str]) -> None:
        """A bucket event named paths: reload (off the delivering thread) when one is a data file
        directly under this sandbox's prefix."""
        base = self.prefix + '/'
        if any(p.startswith(base) and '/' not in p[len(base):] for p in paths):
            threading.Thread(target=self.reload, daemon=True, name='DuckDB-StorageReload').start()

    def _signature(self, files: List[Dict]) -> Dict[str, tuple]:
        sig = {}
        if self.prefix is not None:
            from sajha.core.storage import get_storage
            backend = get_storage()
            for f in files:
                try:
                    sig[f['filename']] = (float(backend.get_modified_time(f['file_path'])), None)
                except Exception:
                    pass
            return sig
        for f in files:
            try:
                st = os.stat(f['file_path'])
                sig[f['filename']] = (st.st_mtime, st.st_size)
            except OSError:
                pass
        return sig

    def _load_storage(self, conn, files: List[Dict]) -> Dict[str, Dict[str, Any]]:
        """Stage each storage file into a temporary local directory, copy it into its table,
        delete the staged copy. Files over the size limits are skipped."""
        import shutil
        import tempfile
        from sajha.core.storage import get_storage
        backend = get_storage()
        max_file, max_total, stage_dir = _stage_limits()
        if stage_dir:
            os.makedirs(stage_dir, exist_ok=True)
        tmp = tempfile.mkdtemp(prefix='sajha-duckdb-', dir=stage_dir)
        states: Dict[str, Dict[str, Any]] = {}
        total = 0
        try:
            for f in files:
                table = _table_name_for(f['filename'])
                try:
                    mtime = float(backend.get_modified_time(f['file_path']))
                    data = backend.read_bytes(f['file_path'])
                    if max_file and len(data) > max_file:
                        logger.warning(f"DuckDB: {f['file_path']} is {_format_file_size(len(data))}, over "
                                       f"data.duckdb.stage_max_file_mb; skipped")
                        continue
                    if max_total and total + len(data) > max_total:
                        logger.warning(f"DuckDB: {f['file_path']} would pass data.duckdb.stage_max_total_mb "
                                       f"for one load; skipped")
                        continue
                    total += len(data)
                    local = os.path.join(tmp, f['filename'])
                    with open(local, 'wb') as fh:
                        fh.write(data)
                    del data
                    conn.execute(
                        f"CREATE OR REPLACE TABLE {sq.quote_identifier(table)} AS "
                        f"SELECT * FROM {_LOADERS[f['file_type']]}", [local])
                    size = os.path.getsize(local)
                    os.unlink(local)
                    states[f['filename']] = {'mtime': mtime, 'size': size, 'sig': (mtime, None),
                                             'view_name': table, 'table_name': table,
                                             'file_type': f['file_type'], 'file_path': f['file_path'],
                                             'source': 'storage'}
                except Exception as e:
                    logger.error(f"DuckDB: could not load {f['file_path']} from storage: {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return states

    def reload(self) -> Dict[str, Dict[str, Any]]:
        """Load every data file into a new sandbox, lock it, and swap it in."""
        files = scan_data_files(self.data_directory)
        conn = duckdb.connect(':memory:')
        states: Dict[str, Dict[str, Any]] = {}
        if self.prefix is not None:
            states = self._load_storage(conn, files)
            files = []
        for f in files:
            table = _table_name_for(f['filename'])
            try:
                conn.execute(
                    f"CREATE OR REPLACE TABLE {sq.quote_identifier(table)} AS "
                    f"SELECT * FROM {_LOADERS[f['file_type']]}", [f['file_path']])
                st = os.stat(f['file_path'])
                states[f['filename']] = {'mtime': st.st_mtime, 'size': st.st_size,
                                         'view_name': table, 'table_name': table,
                                         'file_type': f['file_type'], 'file_path': f['file_path']}
            except Exception as e:
                logger.error(f"DuckDB: could not load {f['file_path']}: {e}")
        conn.execute("SET enable_external_access = false")
        conn.execute("SET lock_configuration = true")
        with self._lock:
            self._conn, self.file_states = conn, states
        logger.info(f"DuckDB sandbox for {self.data_directory}: {len(states)} tables loaded")
        return states

    def cursor(self):
        """A cursor (own thread-safe handle) on the current sandbox."""
        with self._lock:
            return self._conn.cursor()

    def changed(self) -> bool:
        current = self._signature(scan_data_files(self.data_directory))
        known = {n: s.get('sig') or (s['mtime'], s['size']) for n, s in self.file_states.items()}
        return current != known

    def start_auto_refresh(self, interval: int):
        with self._lock:
            if self._refresh_thread and self._refresh_thread.is_alive():
                return
            self._stop.clear()
            self._refresh_thread = threading.Thread(
                target=self._refresh_worker, args=(max(1, int(interval)),),
                daemon=True, name="DuckDB-AutoRefresh")
            self._refresh_thread.start()

    def stop_auto_refresh(self):
        self._stop.set()

    def _refresh_worker(self, interval: int):
        while not self._stop.wait(interval):
            try:
                if self.changed():
                    self.reload()
            except Exception as e:
                logger.error(f"DuckDB auto-refresh error: {e}", exc_info=True)


class DuckDbBaseTool(BaseMCPTool):
    """
    Base class for DuckDB tools with shared functionality
    """

    def __init__(self, config: Dict = None):
        """Initialize DuckDB base tool"""
        super().__init__(config)

        # Data directory for CSV, Parquet, JSON files
        # resolve_placeholders: a config read straight from disk still carries
        # ${data.duckdb.dir:./data/duckdb}; never use (and mkdir) that text literally
        from sajha.core.config import resolve_placeholders, _get
        self.data_directory = resolve_placeholders(
            self.config.get('data_directory') or _get('data.duckdb.dir', './data/duckdb'))
        if '${' in self.data_directory:
            self.data_directory = _get('data.duckdb.dir', './data/duckdb')

        # Auto-refresh configuration
        self.auto_refresh_enabled = self.config.get('auto_refresh_enabled', True)
        self.auto_refresh_interval = self.config.get('auto_refresh_interval', 600)  # Default: 10 minutes (600 seconds)

        # Ensure a local data directory exists (a storage:// one lives on the storage backend)
        if storage_prefix(self.data_directory) is None:
            os.makedirs(self.data_directory, exist_ok=True)

        self.sandbox = DuckDbSandbox.for_directory(self.data_directory)
        if self.auto_refresh_enabled:
            self.sandbox.start_auto_refresh(self.auto_refresh_interval)

    @property
    def _file_states(self) -> Dict[str, Dict[str, Any]]:
        return self.sandbox.file_states

    def _get_connection(self):
        """A cursor on the shared, locked-down sandbox."""
        return self.sandbox.cursor()

    def _initialize_views_from_files(self):
        """(Re)load every data file into a fresh sandbox."""
        return self.sandbox.reload()

    def _check_and_sync_views(self):
        """Reload the sandbox when a data file was added, removed or changed."""
        if self.sandbox.changed():
            self.sandbox.reload()

    def _scan_data_files(self, file_type: str = 'all') -> List[Dict]:
        return scan_data_files(self.data_directory, file_type)

    def _format_file_size(self, size_bytes: int) -> str:
        return _format_file_size(size_bytes)

    # ── catalog lookups: caller names are matched here, then used quoted ───────

    def _catalog_tables(self, conn, include_system: bool = False) -> List[tuple]:
        sql = "SELECT table_schema, table_name, table_type FROM information_schema.tables"
        if not include_system:
            sql += " WHERE table_schema = 'main'"
        return conn.execute(sql + " ORDER BY table_schema, table_name").fetchall()

    def _resolve_table(self, conn, name: Any) -> tuple:
        """``(catalog name, table_type)`` for a table in the ``main`` schema, else an error."""
        if not isinstance(name, str) or not name:
            raise sq.OLAPQueryError("table_name must be a non-empty string")
        rows = conn.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = 'main' AND lower(table_name) = lower(?)", [name]).fetchall()
        if not rows:
            known = [r[1] for r in self._catalog_tables(conn)]
            raise sq.OLAPQueryError(f"Unknown table {name!r}. Available: {known}")
        return rows[0][0], rows[0][1]

    def _table_columns(self, conn, table: str) -> Dict[str, str]:
        """``{lower-case name: (catalog name, data type)}`` for a catalog table."""
        rows = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ? ORDER BY ordinal_position",
            [table]).fetchall()
        return {r[0].lower(): (r[0], r[1]) for r in rows}

    def _resolve_column(self, columns: Dict[str, tuple], name: Any, table: str) -> str:
        if not isinstance(name, str) or name.lower() not in columns:
            raise sq.OLAPQueryError(
                f"Unknown column {name!r} in table {table!r}. "
                f"Available: {[c[0] for c in columns.values()]}")
        return columns[name.lower()][0]

    def close(self):
        """Stop auto-refresh for this tool's sandbox."""
        self.sandbox.stop_auto_refresh()


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
        include_system = bool(arguments.get('include_system_tables', False))

        try:
            conn = self._get_connection()
            tables = []
            for schema, name, ttype in self._catalog_tables(conn, include_system):
                table_info = {
                    'name': name,
                    'type': 'view' if str(ttype).lower() == 'view' else 'table',
                    'schema': schema
                }
                try:
                    qualified = f"{sq.quote_identifier(schema)}.{sq.quote_identifier(name)}"
                    count_result = conn.execute(f"SELECT COUNT(*) FROM {qualified}").fetchone()
                    table_info['row_count'] = count_result[0] if count_result else 0
                except Exception as e:
                    self.logger.debug(f"No row count for {schema}.{name}: {e}")
                    table_info['row_count'] = None
                tables.append(table_info)

            return {
                'tables': tables,
                'total_count': len(tables)
            }

        except Exception as e:
            self.logger.error(f"Failed to list tables: {e}", exc_info=True)
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
        include_sample = bool(arguments.get('include_sample_data', False))
        sample_size = sq.integer(arguments.get('sample_size', 5), 'sample_size', 1, 100)

        try:
            conn = self._get_connection()
            table_name, ttype = self._resolve_table(conn, arguments.get('table_name'))
            table_type = 'view' if str(ttype).lower() == 'view' else 'table'
            quoted = sq.quote_identifier(table_name)

            # Get column information
            describe_result = conn.execute(f"DESCRIBE {quoted}").fetchall()

            columns = []
            for row in describe_result:
                column_info = {
                    'column_name': row[0],
                    'data_type': row[1],
                    'nullable': row[2] == 'YES' if len(row) > 2 else True,
                    'is_primary_key': len(row) > 3 and row[3] == 'PRI'
                }
                if len(row) > 4 and row[4]:
                    column_info['default_value'] = str(row[4])
                columns.append(column_info)

            row_count = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]

            result = {
                'table_name': table_name,
                'table_type': table_type,
                'columns': columns,
                'row_count': row_count
            }

            # Get sample data if requested
            if include_sample:
                result['sample_data'] = _records(
                    conn.execute(f"SELECT * FROM {quoted} LIMIT ?", [sample_size]))

            return result

        except Exception as e:
            self.logger.error(f"Failed to describe table: {e}", exc_info=True)
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
        """Execute SQL query: exactly one read-only statement, in the sandbox."""
        limit = sq.integer(arguments.get('limit', 100), 'limit', 1, 10000)

        conn = self._get_connection()
        # One statement that DuckDB's parser classes as SELECT/EXPLAIN (no ";"-chained
        # DDL/DML, COPY, ATTACH, SET, INSTALL ...); file and URL table functions are
        # refused by the sandbox (external access disabled and locked).
        sql_query = sq.read_only_sql(conn, arguments.get('sql_query'), limit)

        try:
            start_time = time.time()
            result = conn.execute(sql_query)
            columns = [d[0] for d in result.description] if result.description else []
            fetched = result.fetchmany(limit + 1)
            limited = len(fetched) > limit
            rows = [dict(zip(columns, r)) for r in fetched[:limit]]

            execution_time = (time.time() - start_time) * 1000  # Convert to ms

            return {
                'query': sql_query,
                'columns': columns,
                'rows': rows,
                'row_count': len(rows),
                'execution_time_ms': round(execution_time, 2),
                'limited': limited or len(rows) >= limit
            }

        except Exception as e:
            self.logger.error(f"Failed to execute query: {e}", exc_info=True)
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
        reload_external = bool(arguments.get('reload_external_files', False))

        try:
            # Reload external files if requested (a fresh, locked-down sandbox)
            if reload_external:
                self.logger.info("Reloading external data files...")
                self._initialize_views_from_files()
            conn = self._get_connection()
            refreshed_views = []

            if view_name:
                views = [self._resolve_table(conn, view_name)[0]]
            else:
                views = [row[1] for row in self._catalog_tables(conn)]

            for view in views:
                try:
                    start_time = time.time()
                    count_result = conn.execute(
                        f"SELECT COUNT(*) FROM {sq.quote_identifier(view)}").fetchone()
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
            self.logger.error(f"Failed to refresh views: {e}", exc_info=True)
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
        requested = arguments.get('columns') or []
        include_percentiles = bool(arguments.get('include_percentiles', True))
        if not isinstance(requested, list):
            raise sq.OLAPQueryError("columns must be a list of column names")

        try:
            conn = self._get_connection()
            table_name, _ = self._resolve_table(conn, arguments.get('table_name'))
            quoted_table = sq.quote_identifier(table_name)
            catalog = self._table_columns(conn, table_name)
            if requested:
                all_columns = [self._resolve_column(catalog, c, table_name) for c in requested]
            else:
                all_columns = [c[0] for c in catalog.values()]
            types = {c[0]: c[1] for c in catalog.values()}

            total_rows = conn.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()[0]

            column_statistics = {}

            for col in all_columns:
                q = sq.quote_identifier(col)
                stats_parts = [
                    f"COUNT({q}) as count",
                    f"COUNT(*) - COUNT({q}) as null_count",
                    f"MIN({q}) as min",
                    f"MAX({q}) as max",
                    f"COUNT(DISTINCT {q}) as unique_count"
                ]
                try:
                    try:
                        numeric_stats = [f"AVG({q}) as mean", f"STDDEV({q}) as std_dev"]
                        if include_percentiles:
                            numeric_stats.extend([
                                f"PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {q}) as percentile_25",
                                f"PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY {q}) as median",
                                f"PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {q}) as percentile_75"
                            ])
                        stats = conn.execute(
                            f"SELECT {', '.join(stats_parts + numeric_stats)} FROM {quoted_table}").fetchone()

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

                    except Exception:
                        # Non-numeric column (AVG/percentiles do not apply)
                        stats = conn.execute(
                            f"SELECT {', '.join(stats_parts)} FROM {quoted_table}").fetchone()
                        column_statistics[col] = {
                            'count': stats[0],
                            'null_count': stats[1],
                            'min': stats[2],
                            'max': stats[3],
                            'unique_count': stats[4],
                            'data_type': 'non-numeric'
                        }
                    column_statistics[col]['sql_type'] = types.get(col)

                except Exception as e:
                    self.logger.warning(f"Failed to get stats for column {col}: {e}", exc_info=True)
                    continue

            return {
                'table_name': table_name,
                'total_rows': total_rows,
                'column_statistics': column_statistics
            }

        except Exception as e:
            self.logger.error(f"Failed to get statistics: {e}", exc_info=True)
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
        aggregations = arguments.get('aggregations')
        group_by = arguments.get('group_by') or []
        having = arguments.get('having')
        order_by = arguments.get('order_by') or []
        limit = sq.integer(arguments.get('limit', 100), 'limit', 1, 10000)
        if not isinstance(aggregations, dict) or not aggregations:
            raise sq.OLAPQueryError("aggregations must be an object of {column: function}")
        if not isinstance(group_by, list) or not isinstance(order_by, list):
            raise sq.OLAPQueryError("group_by and order_by must be lists")

        try:
            start_time = time.time()
            conn = self._get_connection()
            table_name, _ = self._resolve_table(conn, arguments.get('table_name'))
            catalog = self._table_columns(conn, table_name)

            # Build aggregation expressions: catalog columns, allowlisted functions
            agg_expressions = []
            outputs: Dict[str, str] = {}          # lower-case output name -> SQL expression
            for col, func in aggregations.items():
                column = self._resolve_column(catalog, col, table_name)
                func_upper = str(func).strip().upper()
                if func_upper not in _AGGREGATES:
                    raise sq.OLAPQueryError(
                        f"Unsupported aggregation {func!r} for {col!r}. Allowed: "
                        f"{sorted(f.lower() for f in _AGGREGATES)}")
                expr = _AGGREGATES[func_upper].format(c=sq.quote_identifier(column))
                alias = f"{func_upper.lower()}_{column}"
                agg_expressions.append(f"{expr} AS {sq.quote_identifier(alias)}")
                outputs[alias.lower()] = expr

            groups = [self._resolve_column(catalog, g, table_name) for g in group_by]
            for g in groups:
                outputs.setdefault(g.lower(), sq.quote_identifier(g))
            quoted_groups = [sq.quote_identifier(g) for g in groups]

            select_items = quoted_groups + agg_expressions
            query = f"SELECT {', '.join(select_items)} FROM {sq.quote_identifier(table_name)}"
            if quoted_groups:
                query += f" GROUP BY {', '.join(quoted_groups)}"

            # HAVING: "<output> <op> <number or 'text'>" joined by AND; values are bound
            params: List[Any] = []
            if having:
                if not isinstance(having, str):
                    raise sq.OLAPQueryError("having must be a string")
                conditions = []
                for part in re.split(r"\s+AND\s+", having.strip(), flags=re.IGNORECASE):
                    m = _HAVING_CONDITION.match(part)
                    if not m or m.group(1).lower() not in outputs:
                        raise sq.OLAPQueryError(
                            f"having must be '<name> <op> <value>' conditions joined by AND, "
                            f"where <name> is one of {sorted(outputs)} and <op> one of "
                            f"=, !=, <>, >, <, >=, <=; got {part!r}")
                    raw = m.group(3)
                    value = raw[1:-1].replace("''", "'") if raw.startswith("'") else (
                        float(raw) if '.' in raw else int(raw))
                    params.append(value)
                    conditions.append(f"{outputs[m.group(1).lower()]} {m.group(2)} ?")
                query += f" HAVING {' AND '.join(conditions)}"

            if order_by:
                order_clauses = []
                for order in order_by:
                    if not isinstance(order, dict):
                        raise sq.OLAPQueryError("each order_by entry must be {column, direction}")
                    col = order.get('column')
                    if not isinstance(col, str) or col.lower() not in outputs:
                        raise sq.OLAPQueryError(
                            f"order_by column must be a group_by column or an aggregate "
                            f"output: {sorted(outputs)}; got {col!r}")
                    direction = sq.direction(order.get('direction'), 'ASC')
                    order_clauses.append(f"{outputs[col.lower()]} {direction}")
                query += f" ORDER BY {', '.join(order_clauses)}"

            query += " LIMIT ?"
            params.append(limit)

            records = _records(conn.execute(query, params))

            execution_time = (time.time() - start_time) * 1000

            return {
                'table_name': table_name,
                'aggregations_applied': aggregations,
                'grouped_by': groups,
                'results': records,
                'row_count': len(records),
                'execution_time_ms': round(execution_time, 2)
            }

        except Exception as e:
            self.logger.error(f"Failed to perform aggregation: {e}", exc_info=True)
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

            # Which files are loaded (as tables in the sandbox)
            try:
                conn = self._get_connection()
                loaded_tables = {row[1] for row in self._catalog_tables(conn)}
                for file_info in files:
                    table_name = _table_name_for(file_info['filename'])
                    file_info['is_loaded'] = table_name in loaded_tables
                    if file_info['is_loaded']:
                        file_info['table_name'] = table_name
            except Exception as e:
                self.logger.warning(f"Could not read the loaded tables: {e}")

            if not include_metadata:
                # the summary above still counts sizes; the per-file size and date are dropped
                for file_info in files:
                    for key in ('file_size_bytes', 'file_size_human', 'modified_date'):
                        file_info.pop(key, None)

            return {
                'data_directory': self.data_directory,
                'files': files,
                'total_files': len(files),
                'summary': summary
            }

        except Exception as e:
            self.logger.error(f"Failed to list files: {e}", exc_info=True)
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