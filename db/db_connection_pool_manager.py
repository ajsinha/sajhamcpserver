import logging
import hashlib
import json
import threading
import weakref
import atexit
from typing import Dict, Optional, Any, List, Tuple, Union
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from contextlib import contextmanager
import pickle

# Import the DatabaseConnectionPool and related classes from previous implementation
from core.db.db_connection_pool import (
    DatabaseConnectionPool,
    DatabaseType,
    PoolConfig,
    ConnectionWrapper,
    PoolStatistics
)

logger = logging.getLogger(__name__)


@dataclass
class ConnectionConfig:
    """Configuration for a database connection."""
    db_type: DatabaseType
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    user: Optional[str] = None
    password: Optional[str] = None
    # Additional connection parameters
    charset: Optional[str] = None
    autocommit: bool = False
    ssl: bool = False
    ssl_ca: Optional[str] = None
    ssl_cert: Optional[str] = None
    ssl_key: Optional[str] = None
    connection_timeout: int = 10
    socket_timeout: int = 0
    application_name: Optional[str] = None

    def to_key(self) -> str:
        """Generate a unique key for this configuration."""
        # Create a dictionary of non-sensitive config items for the key
        key_dict = {
            'db_type': self.db_type.value,
            'host': self.host,
            'port': self.port,
            'database': self.database,
            'user': self.user,
            # Don't include password in the key for security
            'charset': self.charset,
            'autocommit': self.autocommit,
            'ssl': self.ssl,
            'ssl_ca': self.ssl_ca,
            'ssl_cert': self.ssl_cert,
            'ssl_key': self.ssl_key,
            'connection_timeout': self.connection_timeout,
            'socket_timeout': self.socket_timeout,
            'application_name': self.application_name
        }

        # Create a stable JSON representation
        key_json = json.dumps(key_dict, sort_keys=True)

        # Generate SHA256 hash for the key
        return hashlib.sha256(key_json.encode()).hexdigest()

    def to_connection_kwargs(self) -> Dict[str, Any]:
        """Convert to kwargs suitable for database connection."""
        kwargs = {}

        if self.db_type == DatabaseType.POSTGRESQL:
            if self.host:
                kwargs['host'] = self.host
            if self.port:
                kwargs['port'] = self.port
            if self.database:
                kwargs['database'] = self.database
            if self.user:
                kwargs['user'] = self.user
            if self.password:
                kwargs['password'] = self.password
            if self.application_name:
                kwargs['application_name'] = self.application_name
            if self.ssl:
                kwargs['sslmode'] = 'require'
                if self.ssl_ca:
                    kwargs['sslrootcert'] = self.ssl_ca
                if self.ssl_cert:
                    kwargs['sslcert'] = self.ssl_cert
                if self.ssl_key:
                    kwargs['sslkey'] = self.ssl_key

        elif self.db_type == DatabaseType.MYSQL:
            if self.host:
                kwargs['host'] = self.host
            if self.port:
                kwargs['port'] = self.port
            if self.database:
                kwargs['database'] = self.database
            if self.user:
                kwargs['user'] = self.user
            if self.password:
                kwargs['password'] = self.password
            if self.charset:
                kwargs['charset'] = self.charset
            kwargs['autocommit'] = self.autocommit
            if self.ssl:
                ssl_dict = {}
                if self.ssl_ca:
                    ssl_dict['ca'] = self.ssl_ca
                if self.ssl_cert:
                    ssl_dict['cert'] = self.ssl_cert
                if self.ssl_key:
                    ssl_dict['key'] = self.ssl_key
                if ssl_dict:
                    kwargs['ssl'] = ssl_dict

        elif self.db_type == DatabaseType.SQLITE:
            kwargs['database'] = self.database or ':memory:'
            kwargs['timeout'] = self.connection_timeout

        elif self.db_type == DatabaseType.SQLSERVER:
            # Build connection string for SQL Server
            conn_str_parts = []
            conn_str_parts.append(f"DRIVER={{ODBC Driver 17 for SQL Server}}")
            if self.host:
                conn_str_parts.append(f"SERVER={self.host},{self.port or 1433}")
            if self.database:
                conn_str_parts.append(f"DATABASE={self.database}")
            if self.user:
                conn_str_parts.append(f"UID={self.user}")
            if self.password:
                conn_str_parts.append(f"PWD={self.password}")
            if self.ssl:
                conn_str_parts.append("Encrypt=yes")
                conn_str_parts.append("TrustServerCertificate=yes")
            kwargs['connection_string'] = ';'.join(conn_str_parts)

        elif self.db_type == DatabaseType.ORACLE:
            if self.host and self.port:
                import cx_Oracle
                kwargs['dsn'] = cx_Oracle.makedsn(
                    self.host,
                    self.port,
                    service_name=self.database
                )
            if self.user:
                kwargs['user'] = self.user
            if self.password:
                kwargs['password'] = self.password

        return kwargs


@dataclass
class PoolInfo:
    """Information about a managed pool."""
    pool_key: str
    pool: DatabaseConnectionPool
    config: ConnectionConfig
    pool_config: PoolConfig
    created_time: datetime
    last_accessed_time: datetime
    access_count: int = 0
    reference_count: int = 0

    def update_access(self):
        """Update access statistics."""
        self.last_accessed_time = datetime.now()
        self.access_count += 1


class DBConnectionPoolManager:
    """
    Singleton manager for database connection pools.

    This class manages multiple connection pools, creating new ones as needed
    and reusing existing pools based on connection configuration.

    Features:
    - Singleton pattern ensures only one manager instance
    - Automatic pool creation based on connection config
    - Pool reuse for identical configurations
    - Lazy pool initialization
    - Automatic cleanup of unused pools
    - Thread-safe operations
    - Comprehensive monitoring and statistics
    """

    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        """Implement singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the pool manager."""
        # Only initialize once
        if DBConnectionPoolManager._initialized:
            return

        with DBConnectionPoolManager._lock:
            if DBConnectionPoolManager._initialized:
                return

            logger.info("Initializing DBConnectionPoolManager")

            # Pool storage
            self._pools: Dict[str, PoolInfo] = {}
            self._pool_lock = threading.RLock()

            # Default pool configuration
            self._default_pool_config = PoolConfig(
                min_idle=2,
                max_idle=10,
                max_total=20,
                test_on_borrow=True,
                test_while_idle=True,
                time_between_eviction_runs=60,
                min_evictable_idle_time=300,
                max_connection_lifetime=3600
            )

            # Manager configuration
            self._max_pools = 50  # Maximum number of pools to manage
            self._pool_idle_timeout = 1800  # Remove pools idle for 30 minutes
            self._enable_jmx = True  # Enable monitoring

            # Cleanup thread
            self._cleanup_thread = None
            self._stop_cleanup = threading.Event()
            self._cleanup_interval = 300  # 5 minutes

            # Statistics
            self._total_pools_created = 0
            self._total_pools_destroyed = 0
            self._total_connections_served = 0

            # Weak references for tracking pool usage
            self._pool_references = weakref.WeakValueDictionary()

            # Register cleanup on exit
            atexit.register(self.shutdown)

            # Start cleanup thread
            self._start_cleanup_thread()

            DBConnectionPoolManager._initialized = True

            logger.info("DBConnectionPoolManager initialized successfully")

    def get_pool(self,
                 connection_config: Optional[ConnectionConfig] = None,
                 pool_config: Optional[PoolConfig] = None,
                 **connection_kwargs) -> DatabaseConnectionPool:
        """
        Get or create a connection pool for the given configuration.

        Args:
            connection_config: ConnectionConfig object
            pool_config: Optional PoolConfig for the pool
            **connection_kwargs: Alternative way to specify connection parameters

        Returns:
            DatabaseConnectionPool instance
        """
        # Create ConnectionConfig if not provided
        if connection_config is None:
            if not connection_kwargs:
                raise ValueError("Either connection_config or connection_kwargs must be provided")

            # Extract db_type from kwargs
            db_type_str = connection_kwargs.pop('db_type', None)
            if not db_type_str:
                raise ValueError("db_type must be specified")

            db_type = DatabaseType(db_type_str) if isinstance(db_type_str, str) else db_type_str

            connection_config = ConnectionConfig(
                db_type=db_type,
                host=connection_kwargs.pop('host', None),
                port=connection_kwargs.pop('port', None),
                database=connection_kwargs.pop('database', None),
                user=connection_kwargs.pop('user', None),
                password=connection_kwargs.pop('password', None),
                **connection_kwargs
            )

        # Generate pool key
        pool_key = connection_config.to_key()

        with self._pool_lock:
            # Check if pool already exists
            if pool_key in self._pools:
                pool_info = self._pools[pool_key]
                pool_info.update_access()
                pool_info.reference_count += 1

                logger.debug(f"Reusing existing pool {pool_key[:8]}... "
                             f"(access_count={pool_info.access_count})")

                self._total_connections_served += 1
                return pool_info.pool

            # Check pool limit
            if len(self._pools) >= self._max_pools:
                # Try to evict an idle pool
                self._evict_idle_pool()

                # Check again
                if len(self._pools) >= self._max_pools:
                    raise RuntimeError(f"Maximum number of pools ({self._max_pools}) reached")

            # Create new pool
            logger.info(f"Creating new pool for key {pool_key[:8]}...")

            # Use provided pool config or default
            if pool_config is None:
                pool_config = self._default_pool_config

            # Create the pool
            connection_kwargs = connection_config.to_connection_kwargs()
            pool = DatabaseConnectionPool(
                db_type=connection_config.db_type,
                config=pool_config,
                **connection_kwargs
            )

            # Create pool info
            pool_info = PoolInfo(
                pool_key=pool_key,
                pool=pool,
                config=connection_config,
                pool_config=pool_config,
                created_time=datetime.now(),
                last_accessed_time=datetime.now(),
                access_count=1,
                reference_count=1
            )

            # Store the pool
            self._pools[pool_key] = pool_info
            self._pool_references[pool_key] = pool

            self._total_pools_created += 1
            self._total_connections_served += 1

            logger.info(f"Created new pool {pool_key[:8]}... "
                        f"(total_pools={len(self._pools)})")

            return pool

    def get_pool_by_name(self,
                         name: str,
                         connection_config: ConnectionConfig,
                         pool_config: Optional[PoolConfig] = None) -> DatabaseConnectionPool:
        """
        Get or create a named pool.

        This is an alternative interface that uses a custom name instead of
        auto-generated key.

        Args:
            name: Custom name for the pool
            connection_config: Connection configuration
            pool_config: Optional pool configuration

        Returns:
            DatabaseConnectionPool instance
        """
        # Override the key generation to use the custom name
        with self._pool_lock:
            if name in self._pools:
                pool_info = self._pools[name]
                pool_info.update_access()
                pool_info.reference_count += 1
                return pool_info.pool

            # Create new pool with custom name as key
            pool = self.get_pool(connection_config, pool_config)

            # Update the key in our storage
            original_key = connection_config.to_key()
            if original_key != name and original_key in self._pools:
                pool_info = self._pools.pop(original_key)
                pool_info.pool_key = name
                self._pools[name] = pool_info

            return pool

    @contextmanager
    def get_connection(self,
                       connection_config: Optional[ConnectionConfig] = None,
                       pool_config: Optional[PoolConfig] = None,
                       timeout: Optional[float] = None,
                       **connection_kwargs):
        """
        Get a database connection from a pool (context manager).

        This is a convenience method that gets a pool and then a connection
        from that pool.

        Args:
            connection_config: Connection configuration
            pool_config: Optional pool configuration
            timeout: Timeout for getting connection
            **connection_kwargs: Alternative connection parameters

        Yields:
            Database connection
        """
        pool = self.get_pool(connection_config, pool_config, **connection_kwargs)

        with pool.get_connection(timeout) as conn:
            yield conn

    def remove_pool(self, pool_key: str) -> bool:
        """
        Remove a pool from management.

        Args:
            pool_key: Key of the pool to remove

        Returns:
            True if pool was removed, False if not found
        """
        with self._pool_lock:
            if pool_key not in self._pools:
                return False

            pool_info = self._pools.pop(pool_key)

            # Close the pool
            try:
                pool_info.pool.close()
            except Exception as e:
                logger.error(f"Error closing pool {pool_key[:8]}...: {e}")

            self._total_pools_destroyed += 1

            logger.info(f"Removed pool {pool_key[:8]}...")
            return True

    def clear_idle_pools(self, idle_time_seconds: Optional[int] = None):
        """
        Clear pools that have been idle for specified time.

        Args:
            idle_time_seconds: Idle time threshold (uses default if None)
        """
        idle_time = idle_time_seconds or self._pool_idle_timeout
        now = datetime.now()
        pools_to_remove = []

        with self._pool_lock:
            for pool_key, pool_info in self._pools.items():
                # Check if pool is idle
                idle_duration = (now - pool_info.last_accessed_time).total_seconds()

                if idle_duration > idle_time and pool_info.reference_count == 0:
                    # Check if pool has no active connections
                    status = pool_info.pool.get_pool_status()
                    if status['active_connections'] == 0:
                        pools_to_remove.append(pool_key)

        # Remove idle pools
        removed = 0
        for pool_key in pools_to_remove:
            if self.remove_pool(pool_key):
                removed += 1

        if removed > 0:
            logger.info(f"Cleared {removed} idle pools")

        return removed

    def _evict_idle_pool(self):
        """Evict the least recently used idle pool."""
        with self._pool_lock:
            # Find the least recently used pool with no active connections
            oldest_pool_key = None
            oldest_access_time = datetime.now()

            for pool_key, pool_info in self._pools.items():
                if pool_info.reference_count == 0:
                    status = pool_info.pool.get_pool_status()
                    if status['active_connections'] == 0:
                        if pool_info.last_accessed_time < oldest_access_time:
                            oldest_access_time = pool_info.last_accessed_time
                            oldest_pool_key = pool_key

            if oldest_pool_key:
                self.remove_pool(oldest_pool_key)
                logger.info(f"Evicted idle pool {oldest_pool_key[:8]}...")
                return True

            return False

    def _cleanup_thread_run(self):
        """Background thread for cleaning up idle pools."""
        logger.info("Starting pool cleanup thread")

        while not self._stop_cleanup.is_set():
            try:
                # Wait for cleanup interval
                self._stop_cleanup.wait(self._cleanup_interval)

                if self._stop_cleanup.is_set():
                    break

                # Clear idle pools
                removed = self.clear_idle_pools()

                # Log statistics periodically
                if self._enable_jmx:
                    stats = self.get_statistics()
                    logger.debug(f"Pool manager stats: {stats}")

            except Exception as e:
                logger.error(f"Error in cleanup thread: {e}")

        logger.info("Pool cleanup thread stopped")

    def _start_cleanup_thread(self):
        """Start the background cleanup thread."""
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            return

        self._stop_cleanup.clear()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_thread_run,
            daemon=True,
            name="DBPoolManager-Cleanup"
        )
        self._cleanup_thread.start()

    def set_default_pool_config(self, config: PoolConfig):
        """
        Set the default pool configuration for new pools.

        Args:
            config: Default PoolConfig to use
        """
        self._default_pool_config = config
        logger.info("Updated default pool configuration")

    def set_max_pools(self, max_pools: int):
        """
        Set the maximum number of pools to manage.

        Args:
            max_pools: Maximum number of pools
        """
        if max_pools < 1:
            raise ValueError("max_pools must be at least 1")

        self._max_pools = max_pools
        logger.info(f"Set maximum pools to {max_pools}")

    def set_pool_idle_timeout(self, timeout_seconds: int):
        """
        Set the idle timeout for pools.

        Args:
            timeout_seconds: Idle timeout in seconds
        """
        self._pool_idle_timeout = timeout_seconds
        logger.info(f"Set pool idle timeout to {timeout_seconds} seconds")

    def get_pool_info(self, pool_key: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a specific pool.

        Args:
            pool_key: Key of the pool

        Returns:
            Dictionary with pool information or None if not found
        """
        with self._pool_lock:
            if pool_key not in self._pools:
                return None

            pool_info = self._pools[pool_key]
            status = pool_info.pool.get_pool_status()

            return {
                'pool_key': pool_key,
                'db_type': pool_info.config.db_type.value,
                'database': pool_info.config.database,
                'created_time': pool_info.created_time.isoformat(),
                'last_accessed_time': pool_info.last_accessed_time.isoformat(),
                'access_count': pool_info.access_count,
                'reference_count': pool_info.reference_count,
                'pool_status': status
            }

    def get_all_pools_info(self) -> List[Dict[str, Any]]:
        """
        Get information about all managed pools.

        Returns:
            List of dictionaries with pool information
        """
        with self._pool_lock:
            pools_info = []
            for pool_key in self._pools:
                info = self.get_pool_info(pool_key)
                if info:
                    pools_info.append(info)
            return pools_info

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get manager statistics.

        Returns:
            Dictionary with manager statistics
        """
        with self._pool_lock:
            total_idle = 0
            total_active = 0
            total_connections = 0

            for pool_info in self._pools.values():
                status = pool_info.pool.get_pool_status()
                total_idle += status['idle_connections']
                total_active += status['active_connections']
                total_connections += status['total_connections']

            return {
                'manager_stats': {
                    'total_pools': len(self._pools),
                    'total_pools_created': self._total_pools_created,
                    'total_pools_destroyed': self._total_pools_destroyed,
                    'total_connections_served': self._total_connections_served,
                    'max_pools': self._max_pools,
                    'pool_idle_timeout': self._pool_idle_timeout
                },
                'aggregate_pool_stats': {
                    'total_idle_connections': total_idle,
                    'total_active_connections': total_active,
                    'total_connections': total_connections
                },
                'pools': [
                    {
                        'key': key[:8] + '...',
                        'db_type': info.config.db_type.value,
                        'database': info.config.database,
                        'access_count': info.access_count,
                        'idle': info.pool.get_pool_status()['idle_connections'],
                        'active': info.pool.get_pool_status()['active_connections']
                    }
                    for key, info in self._pools.items()
                ]
            }

    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check on all pools.

        Returns:
            Dictionary with health status
        """
        with self._pool_lock:
            healthy_pools = 0
            unhealthy_pools = []

            for pool_key, pool_info in self._pools.items():
                try:
                    # Try to get a connection
                    with pool_info.pool.get_connection(timeout=5) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT 1")
                        cursor.close()
                    healthy_pools += 1
                except Exception as e:
                    unhealthy_pools.append({
                        'pool_key': pool_key[:8] + '...',
                        'error': str(e)
                    })

            return {
                'status': 'healthy' if not unhealthy_pools else 'degraded',
                'healthy_pools': healthy_pools,
                'unhealthy_pools': unhealthy_pools,
                'total_pools': len(self._pools)
            }

    def shutdown(self):
        """Shutdown the pool manager and close all pools."""
        logger.info("Shutting down DBConnectionPoolManager")

        # Stop cleanup thread
        if self._cleanup_thread:
            self._stop_cleanup.set()
            self._cleanup_thread.join(timeout=5)

        # Close all pools
        with self._pool_lock:
            for pool_key in list(self._pools.keys()):
                self.remove_pool(pool_key)

            self._pools.clear()

        logger.info(f"DBConnectionPoolManager shutdown complete. "
                    f"Total pools created: {self._total_pools_created}, "
                    f"destroyed: {self._total_pools_destroyed}")

    @classmethod
    def reset_instance(cls):
        """Reset the singleton instance (mainly for testing)."""
        with cls._lock:
            if cls._instance:
                cls._instance.shutdown()
            cls._instance = None
            cls._initialized = False


# Convenience function to get the singleton instance
def get_pool_manager() -> DBConnectionPoolManager:
    """Get the singleton DBConnectionPoolManager instance."""
    return DBConnectionPoolManager()


# Example usage
if __name__ == "__main__":
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Get the singleton manager
    manager = get_pool_manager()

    # Example 1: Get pool using ConnectionConfig
    pg_config = ConnectionConfig(
        db_type=DatabaseType.POSTGRESQL,
        host='localhost',
        port=5432,
        database='testdb',
        user='postgres',
        password='password'
    )

    # This creates a new pool
    pool1 = manager.get_pool(pg_config)
    print(f"Got pool 1: {pool1}")

    # This reuses the existing pool (same config)
    pool2 = manager.get_pool(pg_config)
    print(f"Got pool 2: {pool2}")
    print(f"Pools are same: {pool1 is pool2}")  # True

    # Example 2: Get pool using kwargs
    mysql_pool = manager.get_pool(
        db_type='mysql',
        host='localhost',
        port=3306,
        database='mydb',
        user='root',
        password='password'
    )

    # Example 3: Use connection directly with context manager
    with manager.get_connection(
            db_type='postgresql',
            host='localhost',
            database='testdb',
            user='postgres',
            password='password'
    ) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT version()")
        print(f"PostgreSQL version: {cursor.fetchone()}")
        cursor.close()

    # Example 4: Named pools
    named_pool = manager.get_pool_by_name(
        'my_analytics_db',
        ConnectionConfig(
            db_type=DatabaseType.POSTGRESQL,
            host='analytics.server.com',
            database='analytics',
            user='analyst',
            password='secret'
        )
    )

    # Example 5: Custom pool configuration
    custom_pool_config = PoolConfig(
        min_idle=5,
        max_idle=15,
        max_total=30,
        test_on_borrow=True,
        max_wait_time=60
    )

    high_traffic_pool = manager.get_pool(
        connection_config=ConnectionConfig(
            db_type=DatabaseType.MYSQL,
            host='high-traffic.server.com',
            database='busy_db',
            user='app_user',
            password='app_pass'
        ),
        pool_config=custom_pool_config
    )

    # Example 6: Get statistics
    stats = manager.get_statistics()
    print(f"Manager statistics: {json.dumps(stats, indent=2)}")

    # Example 7: Health check
    health = manager.health_check()
    print(f"Health check: {json.dumps(health, indent=2)}")

    # Example 8: Get all pools info
    all_pools = manager.get_all_pools_info()
    for pool_info in all_pools:
        print(f"Pool {pool_info['pool_key'][:8]}...: "
              f"DB={pool_info['database']}, "
              f"Accesses={pool_info['access_count']}")

    # Example 9: Clear idle pools
    manager.set_pool_idle_timeout(60)  # 1 minute for testing
    removed = manager.clear_idle_pools(60)
    print(f"Removed {removed} idle pools")

    # Example 10: Multiple database types with same manager
    databases = [
        ConnectionConfig(
            db_type=DatabaseType.POSTGRESQL,
            host='pg.server.com',
            database='pg_db',
            user='pg_user',
            password='pg_pass'
        ),
        ConnectionConfig(
            db_type=DatabaseType.MYSQL,
            host='mysql.server.com',
            database='mysql_db',
            user='mysql_user',
            password='mysql_pass'
        ),
        ConnectionConfig(
            db_type=DatabaseType.SQLITE,
            database='local.db'
        )
    ]

    # Create pools for all databases
    pools = []
    for db_config in databases:
        pool = manager.get_pool(db_config)
        pools.append(pool)
        print(f"Created pool for {db_config.db_type.value}: {db_config.database}")

    # Use all pools concurrently
    import concurrent.futures


    def use_pool(pool, pool_index):
        """Worker function to use a pool."""
        for i in range(3):
            with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                cursor.close()
                print(f"Pool {pool_index} - Query {i}: {result}")


    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pools)) as executor:
        futures = []
        for i, pool in enumerate(pools):
            futures.append(executor.submit(use_pool, pool, i))
        concurrent.futures.wait(futures)

    # Final statistics
    final_stats = manager.get_statistics()
    print(f"Final statistics: {json.dumps(final_stats, indent=2)}")

    # Cleanup (automatically called on exit)
    # manager.shutdown()