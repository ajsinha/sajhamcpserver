A comprehensive `DatabaseConnectionPool` class that implements connection pooling similar to Apache DBCP with connection validation, eviction, and replenishment capabilities for multiple database backends.This comprehensive `DatabaseConnectionPool` class that implements enterprise-grade connection pooling similar to Apache DBCP has following key features:

## © 2025-2030 Ashutosh Sinha

## Key Features

### 1. **Multi-Database Support**
- PostgreSQL, MySQL, SQLite, Oracle, and SQL Server
- Database-specific optimizations and connection handling
- Automatic driver validation

### 2. **Connection Lifecycle Management**
- **Connection States**: IDLE, IN_USE, TESTING, INVALID, CLOSED
- **Automatic Creation**: Creates connections on demand up to max_total
- **Connection Validation**: Tests connections before borrowing, after returning, and while idle
- **Connection Eviction**: Removes stale, idle, or invalid connections

### 3. **Eviction Policies**
- **Idle Time**: Evict connections idle longer than threshold
- **Lifetime**: Evict connections older than max lifetime
- **Soft Min Idle**: Maintain minimum idle connections
- **LRU**: Least recently used eviction

### 4. **Advanced Features**
- **Abandoned Connection Detection**: Identifies and reclaims connections not returned by dead threads
- **Fair Mode**: FIFO queue for waiting threads
- **LIFO/FIFO**: Configurable idle connection retrieval
- **Connection Pooling Statistics**: Comprehensive metrics and monitoring
- **Thread Safety**: Full thread-safe implementation with locks and semaphores

### 5. **Configuration Options (PoolConfig)**
```python
config = PoolConfig(
    # Pool sizing
    min_idle=2,           # Minimum idle connections
    max_idle=8,           # Maximum idle connections  
    max_total=20,         # Maximum total connections
    
    # Validation
    test_on_borrow=True,  # Test before giving to client
    test_on_return=False, # Test when returning
    test_while_idle=True, # Test idle connections periodically
    validation_query=None,# Custom validation query
    
    # Eviction
    time_between_eviction_runs=30,  # Seconds
    min_evictable_idle_time=300,    # Seconds
    max_connection_lifetime=3600,   # Seconds
    
    # Behavior
    block_when_exhausted=True,      # Wait for connections
    max_wait_time=30,                # Max wait seconds
    abandoned_remove=True,          # Remove abandoned
    abandoned_timeout=300            # Abandoned timeout seconds
)
```

## Usage Examples

### Basic Usage with Context Manager
```python
# Create pool
pool = DatabaseConnectionPool(
    DatabaseType.POSTGRESQL,
    config=config,
    host='localhost',
    database='mydb',
    user='user',
    password='pass'
)

# Use connection - automatically returned to pool
with pool.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users")
    results = cursor.fetchall()
    cursor.close()
```

### Manual Connection Management
```python
# Borrow connection
wrapper = pool.borrow_connection(timeout=10)
try:
    conn = wrapper.connection
    # Use connection
    cursor = conn.cursor()
    cursor.execute("INSERT INTO logs (message) VALUES (%s)", ("Test",))
    conn.commit()
finally:
    # Always return connection
    pool.return_connection(wrapper)
```

### Convenience Function
```python
# Quick pool creation with defaults
pool = create_pool(
    DatabaseType.MYSQL,
    min_size=5,
    max_size=20,
    host='localhost',
    database='mydb',
    user='root',
    password='password'
)
```

## Key Capabilities Similar to Apache DBCP

### 1. **Connection Validation**
- Configurable validation queries
- Test on borrow, return, and while idle
- Automatic invalidation of bad connections

### 2. **Eviction Thread**
- Background thread for connection maintenance
- Configurable eviction runs
- Multiple eviction policies

### 3. **Abandoned Connection Handling**
- Detects connections held too long
- Automatic reclamation
- Logging of abandoned connections

### 4. **Comprehensive Statistics**
```python
stats = pool.get_pool_status()
# Returns:
{
    'idle_connections': 5,
    'active_connections': 3,
    'total_connections': 8,
    'connections_created': 10,
    'connections_destroyed': 2,
    'average_wait_time': 0.05,
    'max_wait_time': 0.5
}
```

### 5. **Thread Safety**
- Thread-local connection tracking
- Prevents double-borrowing
- Safe concurrent access

## Advanced Features

### 1. **Connection Wrapper**
- Tracks connection metadata
- Use count and error tracking
- Creation and last-used timestamps
- Transaction state tracking

### 2. **Automatic Recovery**
- Replaces expired connections
- Maintains minimum idle connections
- Handles connection failures gracefully

### 3. **Resource Management**
- Automatic cleanup on pool closure
- Graceful shutdown with timeout
- Connection leak prevention

### 4. **Performance Optimizations**
- Connection reuse
- Batch connection creation
- Efficient idle connection management
- Configurable wait strategies

## Benefits Over Basic Connection Handling

1. **Resource Efficiency**: Reuses connections instead of creating new ones
2. **Performance**: Eliminates connection overhead for each operation
3. **Reliability**: Automatic recovery from connection failures
4. **Monitoring**: Built-in statistics and health checks
5. **Scalability**: Handles high concurrency efficiently
6. **Safety**: Prevents connection leaks and abandoned connections

This implementation provides enterprise-grade connection pooling that matches Apache DBCP's capabilities while being Python-native and supporting multiple database backends. It's production-ready and includes all the essential features for robust database connection management.


## Copyright Notice

© 2025 - 2030 Ashutosh Sinha.

All rights reserved. No part of this publication may be reproduced, distributed, or transmitted in any form or by any means, including photocopying, recording, or other electronic or mechanical methods, without the prior written permission of the publisher, except in the case of brief quotations embodied in critical reviews and certain other noncommercial uses permitted by copyright law.
