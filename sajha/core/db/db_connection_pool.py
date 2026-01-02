import logging
import time
import threading
import queue
from queue import Queue, Empty, Full
from typing import Dict, Optional, Any, List, Tuple, Union, Callable
from dataclasses import dataclass, field
from enum import Enum
from contextlib import contextmanager
from datetime import datetime, timedelta
import weakref
import uuid

# Database driver imports
try:
    import psycopg2
    from psycopg2.pool import ThreadedConnectionPool

    HAS_POSTGRESQL = True
except ImportError:
    HAS_POSTGRESQL = False

try:
    import pymysql

    HAS_MYSQL = True
except ImportError:
    HAS_MYSQL = False

try:
    import pyodbc

    HAS_SQLSERVER = True
except ImportError:
    HAS_SQLSERVER = False

try:
    import sqlite3

    HAS_SQLITE = True
except ImportError:
    HAS_SQLITE = False

try:
    import cx_Oracle

    HAS_ORACLE = True
except ImportError:
    HAS_ORACLE = False

logger = logging.getLogger(__name__)


class DatabaseType(Enum):
    """Supported database types."""
    POSTGRESQL = "postgresql"
    MYSQL = "mysql"
    SQLSERVER = "sqlserver"
    SQLITE = "sqlite"
    ORACLE = "oracle"


class ConnectionState(Enum):
    """Connection states."""
    IDLE = "idle"
    IN_USE = "in_use"
    TESTING = "testing"
    INVALID = "invalid"
    CLOSED = "closed"


class EvictionPolicy(Enum):
    """Connection eviction policies."""
    IDLE_TIME = "idle_time"  # Evict connections idle for too long
    LIFETIME = "lifetime"  # Evict connections that are too old
    SOFT_MIN_IDLE = "soft_min_idle"  # Soft minimum idle connections
    LRU = "lru"  # Least recently used


@dataclass
class ConnectionWrapper:
    """Wrapper for database connections with metadata."""
    connection: Any
    connection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: ConnectionState = ConnectionState.IDLE
    created_time: datetime = field(default_factory=datetime.now)
    last_used_time: datetime = field(default_factory=datetime.now)
    last_tested_time: datetime = field(default_factory=datetime.now)
    use_count: int = 0
    error_count: int = 0
    in_transaction: bool = False
    test_query: str = "SELECT 1"
    borrowed_by: Optional[threading.Thread] = None

    def update_last_used(self):
        """Update last used timestamp."""
        self.last_used_time = datetime.now()
        self.use_count += 1

    def is_expired(self, max_lifetime_seconds: int) -> bool:
        """Check if connection has exceeded maximum lifetime."""
        if max_lifetime_seconds <= 0:
            return False
        age = (datetime.now() - self.created_time).total_seconds()
        return age > max_lifetime_seconds

    def is_idle_too_long(self, max_idle_seconds: int) -> bool:
        """Check if connection has been idle for too long."""
        if max_idle_seconds <= 0:
            return False
        idle_time = (datetime.now() - self.last_used_time).total_seconds()
        return idle_time > max_idle_seconds

    def needs_validation(self, test_interval_seconds: int) -> bool:
        """Check if connection needs validation."""
        if test_interval_seconds <= 0:
            return False
        time_since_test = (datetime.now() - self.last_tested_time).total_seconds()
        return time_since_test > test_interval_seconds



@dataclass
class PoolConfig:
    """Configuration for the connection pool."""
    # Basic settings
    min_idle: int = 2  # Minimum idle connections
    max_idle: int = 8  # Maximum idle connections
    max_total: int = 20  # Maximum total connections

    # Connection validation
    test_on_borrow: bool = True  # Test connection before borrowing
    test_on_return: bool = False  # Test connection on return
    test_while_idle: bool = True  # Test idle connections periodically
    validation_query: Optional[str] = None  # Query to validate connections
    validation_timeout: int = 5  # Timeout for validation query (seconds)

    # Eviction settings
    time_between_eviction_runs: int = 30  # Seconds between eviction runs
    min_evictable_idle_time: int = 300  # Min idle time before eviction (seconds)
    max_connection_lifetime: int = 3600  # Max connection lifetime (seconds)
    num_tests_per_eviction_run: int = 3  # Number of connections to test per run
    eviction_policy: EvictionPolicy = EvictionPolicy.IDLE_TIME

    # Behavior settings
    block_when_exhausted: bool = True  # Block when pool is exhausted
    max_wait_time: int = 30  # Max wait time for connection (seconds)
    lifo: bool = True  # Last-in-first-out for idle connections
    fair: bool = False  # Fair mode (FIFO for waiting threads)

    # Connection settings
    connection_timeout: int = 10  # Timeout for creating connections (seconds)
    socket_timeout: int = 0  # Socket timeout (0 = no timeout)

    # Monitoring
    jmx_enabled: bool = True  # Enable JMX-style monitoring
    abandoned_remove: bool = True  # Remove abandoned connections
    abandoned_timeout: int = 300  # Timeout for abandoned connections (seconds)
    log_abandoned: bool = True  # Log abandoned connection info


class PoolStatistics:
    """Statistics for the connection pool."""

    def __init__(self):
        self.connections_created = 0
        self.connections_destroyed = 0
        self.connections_borrowed = 0
        self.connections_returned = 0
        self.connections_validated = 0
        self.connections_invalidated = 0
        self.wait_time_total = 0.0
        self.wait_count = 0
        self.max_wait_time = 0.0
        self._lock = threading.Lock()

    def record_creation(self):
        with self._lock:
            self.connections_created += 1

    def record_destruction(self):
        with self._lock:
            self.connections_destroyed += 1

    def record_borrow(self):
        with self._lock:
            self.connections_borrowed += 1

    def record_return(self):
        with self._lock:
            self.connections_returned += 1

    def record_validation(self):
        with self._lock:
            self.connections_validated += 1

    def record_invalidation(self):
        with self._lock:
            self.connections_invalidated += 1

    def record_wait(self, wait_time: float):
        with self._lock:
            self.wait_time_total += wait_time
            self.wait_count += 1
            self.max_wait_time = max(self.max_wait_time, wait_time)

    def get_average_wait_time(self) -> float:
        with self._lock:
            return self.wait_time_total / self.wait_count if self.wait_count > 0 else 0.0

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                'connections_created': self.connections_created,
                'connections_destroyed': self.connections_destroyed,
                'connections_borrowed': self.connections_borrowed,
                'connections_returned': self.connections_returned,
                'connections_validated': self.connections_validated,
                'connections_invalidated': self.connections_invalidated,
                'average_wait_time': self.get_average_wait_time(),
                'max_wait_time': self.max_wait_time,
                'total_wait_count': self.wait_count
            }


class DatabaseConnectionPool:
    """
    Enterprise-grade database connection pool similar to Apache DBCP.

    Features:
    - Multiple database support (PostgreSQL, MySQL, SQLite, Oracle, SQL Server)
    - Connection validation and health checking
    - Automatic eviction of bad/idle connections
    - Connection lifecycle management
    - Abandoned connection detection and removal
    - Comprehensive statistics and monitoring
    - Thread-safe operations
    """

    def __init__(self,
                 db_type: DatabaseType,
                 config: Optional[PoolConfig] = None,
                 **connection_kwargs):
        """
        Initialize the connection pool.

        Args:
            db_type: Type of database
            config: Pool configuration
            **connection_kwargs: Database connection parameters
        """
        self.db_type = db_type
        self.config = config or PoolConfig()
        self.connection_kwargs = connection_kwargs

        # Validate database driver
        self._validate_database_type()

        # Connection storage
        self._idle_connections = Queue(maxsize=self.config.max_total)
        self._active_connections = {}  # thread_id -> ConnectionWrapper
        self._all_connections = {}  # connection_id -> ConnectionWrapper

        # Thread safety
        self._lock = threading.RLock()
        self._semaphore = threading.Semaphore(self.config.max_total)
        self._waiters = Queue() if self.config.fair else None

        # Pool state
        self._closed = False
        self._total_connections = 0

        # Statistics
        self.stats = PoolStatistics()

        # Eviction thread
        self._eviction_thread = None
        self._stop_eviction = threading.Event()

        # Abandoned connection tracking
        self._abandoned_tracker = weakref.WeakValueDictionary()

        # Initialize the pool
        self._initialize_pool()

    def _validate_database_type(self):
        """Validate that required database driver is installed."""
        if self.db_type == DatabaseType.POSTGRESQL and not HAS_POSTGRESQL:
            raise ImportError("PostgreSQL support requires 'psycopg2' package")
        elif self.db_type == DatabaseType.MYSQL and not HAS_MYSQL:
            raise ImportError("MySQL support requires 'pymysql' package")
        elif self.db_type == DatabaseType.SQLSERVER and not HAS_SQLSERVER:
            raise ImportError("SQL Server support requires 'pyodbc' package")
        elif self.db_type == DatabaseType.SQLITE and not HAS_SQLITE:
            raise ImportError("SQLite support should be built-in")
        elif self.db_type == DatabaseType.ORACLE and not HAS_ORACLE:
            raise ImportError("Oracle support requires 'cx_Oracle' package")

    def _initialize_pool(self):
        """Initialize the connection pool with minimum connections."""
        logger.info(f"Initializing connection pool for {self.db_type.value}")

        # Create initial connections
        for i in range(self.config.min_idle):
            try:
                conn_wrapper = self._create_connection()
                if conn_wrapper:
                    self._idle_connections.put(conn_wrapper)
                    logger.debug(f"Created initial connection {i + 1}/{self.config.min_idle}")
            except Exception as e:
                logger.warning(f"Failed to create initial connection: {e}")

        # Start eviction thread
        if self.config.time_between_eviction_runs > 0:
            self._start_eviction_thread()

    def _create_connection(self) -> Optional[ConnectionWrapper]:
        """Create a new database connection."""
        with self._lock:
            if self._closed:
                raise RuntimeError("Pool is closed")

            if self._total_connections >= self.config.max_total:
                return None

        try:
            # Create raw connection based on database type
            if self.db_type == DatabaseType.POSTGRESQL:
                conn = psycopg2.connect(**self.connection_kwargs)
                test_query = "SELECT 1"

            elif self.db_type == DatabaseType.MYSQL:
                conn = pymysql.connect(**self.connection_kwargs)
                test_query = "SELECT 1"

            elif self.db_type == DatabaseType.SQLITE:
                conn = sqlite3.connect(**self.connection_kwargs)
                test_query = "SELECT 1"

            elif self.db_type == DatabaseType.SQLSERVER:
                conn_str = self.connection_kwargs.get('connection_string', '')
                conn = pyodbc.connect(conn_str)
                test_query = "SELECT 1"

            elif self.db_type == DatabaseType.ORACLE:
                conn = cx_Oracle.connect(**self.connection_kwargs)
                test_query = "SELECT 1 FROM DUAL"

            else:
                raise ValueError(f"Unsupported database type: {self.db_type}")

            # Set connection properties
            if self.config.socket_timeout > 0:
                self._set_socket_timeout(conn, self.config.socket_timeout)

            # Create wrapper
            wrapper = ConnectionWrapper(
                connection=conn,
                test_query=self.config.validation_query or test_query
            )

            # Register connection
            with self._lock:
                self._all_connections[wrapper.connection_id] = wrapper
                self._total_connections += 1

            self.stats.record_creation()
            logger.debug(f"Created new connection {wrapper.connection_id}")

            return wrapper

        except Exception as e:
            logger.error(f"Failed to create connection: {e}")
            self.stats.record_invalidation()
            raise

    def _set_socket_timeout(self, conn: Any, timeout: int):
        """Set socket timeout on the connection."""
        if self.db_type == DatabaseType.POSTGRESQL:
            conn.set_session(readonly=False, autocommit=False)
            cursor = conn.cursor()
            cursor.execute(f"SET statement_timeout = {timeout * 1000}")
            cursor.close()
        elif self.db_type == DatabaseType.MYSQL:
            conn.query(f"SET SESSION wait_timeout = {timeout}")

    def _validate_connection(self, wrapper: ConnectionWrapper) -> bool:
        """Validate a connection is still good."""
        if wrapper.state == ConnectionState.CLOSED:
            return False

        wrapper.state = ConnectionState.TESTING

        try:
            cursor = wrapper.connection.cursor()
            cursor.execute(wrapper.test_query)
            cursor.fetchone()
            cursor.close()

            wrapper.last_tested_time = datetime.now()
            wrapper.state = ConnectionState.IDLE
            self.stats.record_validation()

            return True

        except Exception as e:
            logger.debug(f"Connection {wrapper.connection_id} validation failed: {e}")
            wrapper.state = ConnectionState.INVALID
            wrapper.error_count += 1
            self.stats.record_invalidation()
            return False

    def _destroy_connection(self, wrapper: ConnectionWrapper):
        """Destroy a connection and remove from pool."""
        if wrapper.state == ConnectionState.CLOSED:
            return

        try:
            wrapper.connection.close()
        except:
            pass

        wrapper.state = ConnectionState.CLOSED

        with self._lock:
            # Remove from all tracking
            self._all_connections.pop(wrapper.connection_id, None)
            self._total_connections -= 1

        self.stats.record_destruction()
        logger.debug(f"Destroyed connection {wrapper.connection_id}")

    def _ensure_min_idle(self):
        """Ensure minimum idle connections are maintained."""
        with self._lock:
            current_idle = self._idle_connections.qsize()
            current_active = len(self._active_connections)
            current_total = current_idle + current_active

            needed = max(0, min(
                self.config.min_idle - current_idle,
                self.config.max_total - current_total
            ))

            for _ in range(needed):
                try:
                    wrapper = self._create_connection()
                    if wrapper:
                        self._idle_connections.put_nowait(wrapper)
                except Full:
                    break
                except Exception as e:
                    logger.warning(f"Failed to create connection for min idle: {e}")

    def _evict_connections(self):
        """Evict idle connections based on eviction policy."""
        evicted = []
        tested = 0
        max_tests = self.config.num_tests_per_eviction_run

        # Collect connections to test
        connections_to_test = []

        for _ in range(self._idle_connections.qsize()):
            try:
                wrapper = self._idle_connections.get_nowait()
                connections_to_test.append(wrapper)
            except Empty:
                break

        # Test and evict connections
        for wrapper in connections_to_test:
            if tested >= max_tests:
                # Put back untested connections
                try:
                    self._idle_connections.put_nowait(wrapper)
                except Full:
                    evicted.append(wrapper)
                continue

            tested += 1
            should_evict = False

            # Check eviction criteria
            if wrapper.is_expired(self.config.max_connection_lifetime):
                should_evict = True
                logger.debug(f"Connection {wrapper.connection_id} exceeded lifetime")

            elif wrapper.is_idle_too_long(self.config.min_evictable_idle_time):
                if self._idle_connections.qsize() > self.config.min_idle:
                    should_evict = True
                    logger.debug(f"Connection {wrapper.connection_id} idle too long")

            elif wrapper.error_count > 3:
                should_evict = True
                logger.debug(f"Connection {wrapper.connection_id} has too many errors")

            elif self.config.test_while_idle and not self._validate_connection(wrapper):
                should_evict = True
                logger.debug(f"Connection {wrapper.connection_id} failed validation")

            if should_evict:
                evicted.append(wrapper)
            else:
                try:
                    self._idle_connections.put_nowait(wrapper)
                except Full:
                    evicted.append(wrapper)

        # Destroy evicted connections
        for wrapper in evicted:
            self._destroy_connection(wrapper)

        # Ensure minimum idle connections
        self._ensure_min_idle()

        return len(evicted)

    def _eviction_thread_run(self):
        """Background thread for connection eviction."""
        logger.info("Starting eviction thread")

        while not self._stop_eviction.is_set():
            try:
                # Wait for configured interval
                self._stop_eviction.wait(self.config.time_between_eviction_runs)

                if self._stop_eviction.is_set():
                    break

                # Run eviction
                evicted = self._evict_connections()
                if evicted > 0:
                    logger.info(f"Evicted {evicted} connections")

                # Check for abandoned connections
                if self.config.abandoned_remove:
                    self._remove_abandoned_connections()

            except Exception as e:
                logger.error(f"Error in eviction thread: {e}")

        logger.info("Eviction thread stopped")

    def _start_eviction_thread(self):
        """Start the background eviction thread."""
        if self._eviction_thread and self._eviction_thread.is_alive():
            return

        self._stop_eviction.clear()
        self._eviction_thread = threading.Thread(
            target=self._eviction_thread_run,
            daemon=True
        )
        self._eviction_thread.start()

    def _remove_abandoned_connections(self):
        """Remove connections that have been abandoned by threads."""
        now = datetime.now()
        abandoned = []

        with self._lock:
            for thread_id, wrapper in list(self._active_connections.items()):
                # Check if thread is still alive
                if wrapper.borrowed_by and not wrapper.borrowed_by.is_alive():
                    abandoned.append((thread_id, wrapper))
                    logger.warning(f"Found abandoned connection from dead thread: {wrapper.connection_id}")

                # Check if connection has been borrowed too long
                elif (now - wrapper.last_used_time).total_seconds() > self.config.abandoned_timeout:
                    abandoned.append((thread_id, wrapper))
                    if self.config.log_abandoned:
                        logger.warning(f"Connection {wrapper.connection_id} abandoned for "
                                       f"{(now - wrapper.last_used_time).total_seconds():.1f} seconds")

            # Return abandoned connections to pool or destroy them
            for thread_id, wrapper in abandoned:
                del self._active_connections[thread_id]

                # Validate and return to pool or destroy
                if self._validate_connection(wrapper):
                    wrapper.state = ConnectionState.IDLE
                    wrapper.borrowed_by = None
                    try:
                        self._idle_connections.put_nowait(wrapper)
                    except Full:
                        self._destroy_connection(wrapper)
                else:
                    self._destroy_connection(wrapper)

    @contextmanager
    def get_connection(self, timeout: Optional[float] = None):
        """
        Get a connection from the pool (context manager).

        Args:
            timeout: Maximum time to wait for a connection

        Yields:
            Database connection object
        """
        conn_wrapper = self.borrow_connection(timeout)
        try:
            yield conn_wrapper.connection
        finally:
            self.return_connection(conn_wrapper)

    def borrow_connection(self, timeout: Optional[float] = None) -> ConnectionWrapper:
        """
        Borrow a connection from the pool.

        Args:
            timeout: Maximum time to wait for a connection

        Returns:
            ConnectionWrapper object
        """
        if self._closed:
            raise RuntimeError("Pool is closed")

        timeout = timeout or self.config.max_wait_time
        start_time = time.time()
        thread_id = threading.get_ident()

        # Check if thread already has a connection
        with self._lock:
            if thread_id in self._active_connections:
                wrapper = self._active_connections[thread_id]
                logger.warning(f"Thread {thread_id} already has connection {wrapper.connection_id}")
                return wrapper

        wrapper = None
        wait_time = 0

        while wrapper is None:
            try:
                # Try to get an idle connection
                remaining_timeout = max(0, timeout - (time.time() - start_time))

                if remaining_timeout <= 0 and self.config.block_when_exhausted:
                    raise TimeoutError("Timeout waiting for connection")

                try:
                    wrapper = self._idle_connections.get(
                        block=self.config.block_when_exhausted,
                        timeout=remaining_timeout if self.config.block_when_exhausted else 0
                    )
                except Empty:
                    # Try to create a new connection if under max_total
                    with self._lock:
                        if self._total_connections < self.config.max_total:
                            wrapper = self._create_connection()

                    if wrapper is None:
                        if not self.config.block_when_exhausted:
                            raise RuntimeError("No connections available")
                        continue

                # Validate connection if required
                if wrapper and self.config.test_on_borrow:
                    if not self._validate_connection(wrapper):
                        self._destroy_connection(wrapper)
                        wrapper = None
                        continue

                # Check if connection needs replacement
                if wrapper and wrapper.is_expired(self.config.max_connection_lifetime):
                    self._destroy_connection(wrapper)
                    wrapper = self._create_connection()

            except TimeoutError:
                wait_time = time.time() - start_time
                self.stats.record_wait(wait_time)
                raise

        # Mark connection as active
        wrapper.state = ConnectionState.IN_USE
        wrapper.borrowed_by = threading.current_thread()
        wrapper.update_last_used()

        with self._lock:
            self._active_connections[thread_id] = wrapper

        wait_time = time.time() - start_time
        if wait_time > 0:
            self.stats.record_wait(wait_time)

        self.stats.record_borrow()
        logger.debug(f"Borrowed connection {wrapper.connection_id} for thread {thread_id}")

        return wrapper

    def return_connection(self, wrapper: ConnectionWrapper):
        """
        Return a connection to the pool.

        Args:
            wrapper: ConnectionWrapper to return
        """
        if self._closed:
            self._destroy_connection(wrapper)
            return

        thread_id = threading.get_ident()

        # Remove from active connections
        with self._lock:
            if thread_id in self._active_connections:
                if self._active_connections[thread_id].connection_id != wrapper.connection_id:
                    logger.warning(f"Thread {thread_id} returning different connection than borrowed")
                del self._active_connections[thread_id]

        # Check if connection should be destroyed
        should_destroy = False

        if wrapper.state == ConnectionState.INVALID:
            should_destroy = True
        elif wrapper.in_transaction:
            # Rollback any open transaction
            try:
                wrapper.connection.rollback()
                wrapper.in_transaction = False
            except:
                should_destroy = True
        elif self.config.test_on_return and not self._validate_connection(wrapper):
            should_destroy = True
        elif self._idle_connections.qsize() >= self.config.max_idle:
            should_destroy = True

        if should_destroy:
            self._destroy_connection(wrapper)
        else:
            wrapper.state = ConnectionState.IDLE
            wrapper.borrowed_by = None

            try:
                self._idle_connections.put_nowait(wrapper)
            except Full:
                self._destroy_connection(wrapper)

        self.stats.record_return()
        logger.debug(f"Returned connection {wrapper.connection_id}")

    def invalidate_connection(self, wrapper: ConnectionWrapper):
        """
        Invalidate a connection, marking it for destruction.

        Args:
            wrapper: ConnectionWrapper to invalidate
        """
        wrapper.state = ConnectionState.INVALID
        self.return_connection(wrapper)

    def get_pool_status(self) -> Dict[str, Any]:
        """Get current pool status and statistics."""
        with self._lock:
            idle_count = self._idle_connections.qsize()
            active_count = len(self._active_connections)

            return {
                'pool_state': 'closed' if self._closed else 'active',
                'idle_connections': idle_count,
                'active_connections': active_count,
                'total_connections': self._total_connections,
                'max_total': self.config.max_total,
                'max_idle': self.config.max_idle,
                'min_idle': self.config.min_idle,
                'statistics': self.stats.get_stats()
            }

    def clear_idle_connections(self):
        """Clear all idle connections from the pool."""
        cleared = 0

        while not self._idle_connections.empty():
            try:
                wrapper = self._idle_connections.get_nowait()
                self._destroy_connection(wrapper)
                cleared += 1
            except Empty:
                break

        logger.info(f"Cleared {cleared} idle connections")
        self._ensure_min_idle()

    def close(self):
        """Close the connection pool and all connections."""
        if self._closed:
            return

        logger.info("Closing connection pool")
        self._closed = True

        # Stop eviction thread
        if self._eviction_thread:
            self._stop_eviction.set()
            self._eviction_thread.join(timeout=5)

        # Close all connections
        with self._lock:
            # Close idle connections
            while not self._idle_connections.empty():
                try:
                    wrapper = self._idle_connections.get_nowait()
                    self._destroy_connection(wrapper)
                except Empty:
                    break

            # Close active connections
            for wrapper in list(self._active_connections.values()):
                self._destroy_connection(wrapper)

            self._active_connections.clear()
            self._all_connections.clear()

        logger.info(f"Connection pool closed. Final stats: {self.stats.get_stats()}")


# Convenience function to create pre-configured pools
def create_pool(db_type: DatabaseType,
                min_size: int = 2,
                max_size: int = 10,
                **connection_kwargs) -> DatabaseConnectionPool:
    """
    Create a pre-configured connection pool.

    Args:
        db_type: Type of database
        min_size: Minimum pool size
        max_size: Maximum pool size
        **connection_kwargs: Database connection parameters

    Returns:
        Configured DatabaseConnectionPool
    """
    config = PoolConfig(
        min_idle=min_size,
        max_idle=max_size,
        max_total=max_size,
        test_on_borrow=True,
        test_while_idle=True,
        time_between_eviction_runs=30,
        min_evictable_idle_time=300,
        max_connection_lifetime=3600
    )

    return DatabaseConnectionPool(db_type, config, **connection_kwargs)


# Example usage
if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Example 1: PostgreSQL pool with custom configuration
    pg_config = PoolConfig(
        min_idle=5,
        max_idle=10,
        max_total=20,
        test_on_borrow=True,
        test_while_idle=True,
        time_between_eviction_runs=60,
        min_evictable_idle_time=300,
        max_connection_lifetime=3600,
        abandoned_remove=True,
        abandoned_timeout=180,
        max_wait_time=30
    )

    pg_pool = DatabaseConnectionPool(
        DatabaseType.POSTGRESQL,
        config=pg_config,
        host='localhost',
        port=5432,
        database='testdb',
        user='postgres',
        password='password'
    )

    # Use connection with context manager
    with pg_pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT version()")
        print(f"PostgreSQL version: {cursor.fetchone()}")
        cursor.close()

    # Check pool status
    print(f"Pool status: {pg_pool.get_pool_status()}")

    # Example 2: MySQL pool with connection validation
    mysql_pool = create_pool(
        DatabaseType.MYSQL,
        min_size=3,
        max_size=15,
        host='localhost',
        port=3306,
        database='testdb',
        user='root',
        password='password'
    )

    # Simulate concurrent usage
    import concurrent.futures


    def worker(pool, worker_id):
        """Worker function to test concurrent access."""
        for i in range(5):
            try:
                with pool.get_connection(timeout=10) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT SLEEP(0.1)")
                    cursor.close()
                    print(f"Worker {worker_id} - Query {i} completed")
            except Exception as e:
                print(f"Worker {worker_id} - Error: {e}")
            time.sleep(0.1)


    # Test with multiple threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for i in range(10):
            futures.append(executor.submit(worker, mysql_pool, i))

        # Wait for all workers to complete
        concurrent.futures.wait(futures)

    # Check final statistics
    print(f"Final pool statistics: {mysql_pool.get_pool_status()}")

    # Example 3: SQLite pool (useful for testing)
    sqlite_config = PoolConfig(
        min_idle=1,
        max_idle=5,
        max_total=10,
        test_on_borrow=False,  # SQLite doesn't need connection testing
        test_while_idle=False
    )

    sqlite_pool = DatabaseConnectionPool(
        DatabaseType.SQLITE,
        config=sqlite_config,
        database=':memory:'  # In-memory database
    )

    # Create test table
    with sqlite_pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT,
                email TEXT
            )
        ''')
        conn.commit()
        cursor.close()

    # Example 4: Oracle pool with abandoned connection removal
    if HAS_ORACLE:
        oracle_config = PoolConfig(
            min_idle=2,
            max_idle=8,
            max_total=15,
            abandoned_remove=True,
            abandoned_timeout=120,
            log_abandoned=True
        )

        oracle_pool = DatabaseConnectionPool(
            DatabaseType.ORACLE,
            config=oracle_config,
            user='scott',
            password='tiger',
            dsn='localhost:1521/XE'
        )

        # Test abandoned connection handling
        wrapper = oracle_pool.borrow_connection()
        # Simulate abandoned connection by not returning it
        time.sleep(130)  # Wait longer than abandoned_timeout

        # The eviction thread should detect and reclaim the connection
        print(f"Oracle pool status: {oracle_pool.get_pool_status()}")

    # Clean up
    pg_pool.close()
    mysql_pool.close()
    sqlite_pool.close()