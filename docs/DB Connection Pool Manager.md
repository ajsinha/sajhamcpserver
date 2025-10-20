A singleton `DBConnectionPoolManager` class that manages multiple connection pool instances, using connection configurations as keys for pool identification and reuse.This comprehensive singleton `DBConnectionPoolManager` class manages multiple database connection pools efficiently. Here are the key features:

## © 2025-2030 Ashutosh Sinha

## Key Features

### 1. **Singleton Pattern**
- Ensures only one manager instance exists globally
- Thread-safe initialization
- Accessible via `get_pool_manager()` function

### 2. **Automatic Pool Management**
- Creates new pools based on unique connection configurations
- Reuses existing pools for identical configurations
- Generates unique keys from connection parameters (excluding passwords for security)

### 3. **Connection Configuration**
- `ConnectionConfig` dataclass for clean configuration management
- Supports all database types (PostgreSQL, MySQL, SQLite, Oracle, SQL Server)
- SSL/TLS support with certificates
- Custom application naming

### 4. **Pool Lifecycle Management**
- Automatic cleanup of idle pools
- Configurable idle timeout
- LRU eviction when pool limit reached
- Reference counting for safe pool removal

### 5. **Advanced Features**
- Named pools for custom identification
- Per-pool custom configuration
- Background cleanup thread
- Comprehensive statistics and monitoring
- Health checks across all pools
- Graceful shutdown with cleanup

## Usage Examples

### Basic Usage - Automatic Pool Creation/Reuse
```python
# Get the singleton manager
manager = get_pool_manager()

# First call creates a new pool
pool1 = manager.get_pool(
    db_type='postgresql',
    host='localhost',
    database='mydb',
    user='user',
    password='pass'
)

# Second call with same config returns existing pool
pool2 = manager.get_pool(
    db_type='postgresql',
    host='localhost',
    database='mydb',
    user='user',
    password='pass'
)

assert pool1 is pool2  # Same pool instance
```

### Using ConnectionConfig
```python
# Define configuration
config = ConnectionConfig(
    db_type=DatabaseType.POSTGRESQL,
    host='localhost',
    port=5432,
    database='testdb',
    user='postgres',
    password='password',
    ssl=True,
    application_name='MyApp'
)

# Get pool
pool = manager.get_pool(config)

# Use connection
with pool.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    results = cursor.fetchall()
```

### Direct Connection Access
```python
# Convenience method - get connection directly
with manager.get_connection(
    db_type='mysql',
    host='localhost',
    database='mydb',
    user='root',
    password='password'
) as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM orders")
    count = cursor.fetchone()[0]
```

### Named Pools
```python
# Create named pool for easy reference
analytics_pool = manager.get_pool_by_name(
    'analytics_db',
    ConnectionConfig(
        db_type=DatabaseType.POSTGRESQL,
        host='analytics.server.com',
        database='analytics',
        user='analyst',
        password='secret'
    )
)

# Later, retrieve by name
pool = manager.get_pool_by_name('analytics_db', config)
```

### Custom Pool Configuration
```python
# High-performance pool configuration
high_perf_config = PoolConfig(
    min_idle=10,
    max_idle=50,
    max_total=100,
    test_on_borrow=False,  # Skip validation for performance
    max_wait_time=5
)

# Create pool with custom config
pool = manager.get_pool(
    connection_config=ConnectionConfig(
        db_type=DatabaseType.MYSQL,
        host='high-traffic.server.com',
        database='busy_db',
        user='app',
        password='pass'
    ),
    pool_config=high_perf_config
)
```

## Key Management Features

### 1. **Automatic Pool Reuse**
The manager generates a unique SHA256 hash key from connection parameters:
- Same configuration = same pool
- Password excluded from key for security
- Efficient pool reuse across application

### 2. **Pool Limits and Eviction**
```python
# Set maximum pools
manager.set_max_pools(50)

# When limit reached, LRU idle pool is evicted
# Pools with active connections are protected
```

### 3. **Idle Pool Cleanup**
```python
# Set idle timeout
manager.set_pool_idle_timeout(1800)  # 30 minutes

# Manual cleanup
removed = manager.clear_idle_pools(300)  # Clear pools idle > 5 min

# Automatic cleanup via background thread every 5 minutes
```

### 4. **Monitoring and Statistics**
```python
# Get comprehensive statistics
stats = manager.get_statistics()
# Returns:
{
    "manager_stats": {
        "total_pools": 5,
        "total_pools_created": 10,
        "total_pools_destroyed": 5,
        "total_connections_served": 1000
    },
    "aggregate_pool_stats": {
        "total_idle_connections": 15,
        "total_active_connections": 8,
        "total_connections": 23
    },
    "pools": [...]
}

# Health check all pools
health = manager.health_check()
# Returns:
{
    "status": "healthy",
    "healthy_pools": 5,
    "unhealthy_pools": [],
    "total_pools": 5
}

# Get specific pool info
info = manager.get_pool_info(pool_key)
```

### 5. **Thread Safety**
- All operations are thread-safe
- Multiple threads can request pools concurrently
- Proper locking ensures consistency

## Configuration Options

### Manager Configuration
```python
manager = get_pool_manager()

# Set defaults for all new pools
manager.set_default_pool_config(PoolConfig(
    min_idle=5,
    max_idle=20,
    max_total=50
))

# Set manager limits
manager.set_max_pools(100)
manager.set_pool_idle_timeout(3600)
```

### ConnectionConfig Parameters
```python
config = ConnectionConfig(
    db_type=DatabaseType.POSTGRESQL,
    host='localhost',
    port=5432,
    database='mydb',
    user='user',
    password='pass',
    
    # Optional parameters
    charset='utf8',
    autocommit=False,
    ssl=True,
    ssl_ca='/path/to/ca.pem',
    ssl_cert='/path/to/cert.pem',
    ssl_key='/path/to/key.pem',
    connection_timeout=10,
    socket_timeout=30,
    application_name='MyApp'
)
```

## Benefits

1. **Resource Efficiency**: Single point of management for all database pools
2. **Automatic Reuse**: No duplicate pools for same configuration
3. **Memory Management**: Automatic cleanup of unused pools
4. **Monitoring**: Centralized statistics and health checks
5. **Thread Safety**: Safe concurrent access from multiple threads
6. **Flexibility**: Support for multiple database types and configurations
7. **Production Ready**: Graceful shutdown, error handling, and logging

## Lifecycle Management

### Automatic Cleanup
- Background thread runs every 5 minutes
- Removes pools idle longer than configured timeout
- Preserves pools with active connections

### Graceful Shutdown
```python
# Automatic on application exit via atexit
# Or manual shutdown
manager.shutdown()
```

This implementation provides enterprise-grade connection pool management with the convenience of automatic pool creation and reuse, making it ideal for applications that connect to multiple databases or have dynamic connection requirements.


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.
