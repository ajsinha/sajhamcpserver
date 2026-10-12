"""
SAJHA MCP Server v3 — Database Engine & Session Factory
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Supports SQLite (default, zero-config) and PostgreSQL (production).
Configured via db.type in application.yml or SAJHA_DB_TYPE env var.
"""

import logging
import threading
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from sqlalchemy import create_engine, event, text
from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

# Module-level singletons — initialized by init_db()
_engine = None
_SessionLocal: sessionmaker = None


# ── the connection pool ─────────────────────────────────────────────
#
# The rule (docs/architecture/Scaling and State.md §7): a database connection is held for the
# shortest time the work needs. One session per unit of work, closed (connection back to the
# pool) as soon as the database part is done, and always closed or rolled back on an exception
# (``session_scope``, ``get_db``, ``release_session``). A pool that runs dry answers quickly:
# a checkout waits at most ``db.pool.timeout_seconds``, then raises ``PoolExhausted`` (an
# ``sqlalchemy.exc.TimeoutError``), which the application answers with HTTP 503 and
# ``Retry-After`` (a JSON-RPC error with retry data on /mcp), never a hang or a 401.

class _PoolCounters:
    """Process-wide pool counters (the gauges read the pool itself)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.exhausted = 0          # checkouts that timed out (sajha_db_pool_exhausted_total)
        self.waiting = 0            # threads waiting for a connection now (approximate)

    def add(self, name: str, n: int) -> None:
        with self.lock:
            setattr(self, name, getattr(self, name) + n)


POOL_COUNTERS = _PoolCounters()


class CountingQueuePool(QueuePool):
    """A QueuePool that counts checkout timeouts and the threads waiting for a connection."""

    def _do_get(self):
        full = self.checkedout() >= self.size() + max(self._max_overflow, 0)
        if full:
            POOL_COUNTERS.add('waiting', 1)
        try:
            return super()._do_get()
        except sa_exc.TimeoutError:
            POOL_COUNTERS.add('exhausted', 1)
            raise
        finally:
            if full:
                POOL_COUNTERS.add('waiting', -1)


#: what a checkout that timed out raises (``QueuePool`` raises it; kept as a name for callers)
PoolExhausted = sa_exc.TimeoutError


def is_pool_exhausted(exc: Optional[BaseException]) -> bool:
    """True when ``exc`` (or an exception it was raised from) is a pool checkout timeout."""
    seen = 0
    while exc is not None and seen < 10:
        if isinstance(exc, sa_exc.TimeoutError):
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


def pool_options(settings) -> Dict[str, Any]:
    """``pool_size``, ``max_overflow`` and ``pool_timeout`` from ``db.pool.*``, validated.

    ``db.pool.max_overflow`` below zero (the default, -1) means "as many as ``db.pool.size``", the
    sizing SAJHA always used on PostgreSQL. An invalid value stops start-up with the key named.
    """
    size = int(getattr(settings, 'db_pool_size', 10))
    overflow = int(getattr(settings, 'db_pool_max_overflow', -1))
    timeout = float(getattr(settings, 'db_pool_timeout_seconds', 5.0))
    if size < 1:
        raise ValueError(f'db.pool.size must be at least 1 (got {size})')
    if overflow < 0:
        overflow = size
    if not (0 < timeout <= 300):
        raise ValueError(f'db.pool.timeout_seconds must be more than 0 and at most 300 (got {timeout})')
    return {'pool_size': size, 'max_overflow': overflow, 'pool_timeout': timeout}


def _redacted(url) -> str:
    try:
        return url.render_as_string(hide_password=True)
    except Exception:
        return '***'


def pool_status() -> Dict[str, Any]:
    """This process's pool: type of database, redacted URL, size, overflow, checked out, waiting,
    checkout timeouts. ``{}`` before ``init_db``. The admin System page and
    ``/api/admin/system/info`` show it; the metrics read it (docs/architecture/Observability.md)."""
    if _engine is None:
        return {}
    pool = _engine.pool
    out: Dict[str, Any] = {'db_type': _engine.dialect.name, 'url': _redacted(_engine.url),
                           'pool_class': type(pool).__name__,
                           'exhausted_total': POOL_COUNTERS.exhausted, 'waiting': POOL_COUNTERS.waiting}
    if isinstance(pool, QueuePool):
        size = pool.size()
        out.update({'size': size, 'max_overflow': pool._max_overflow, 'timeout_seconds': pool.timeout(),
                    'checked_out': pool.checkedout(), 'idle': pool.checkedin(),
                    'overflow_in_use': max(0, pool.checkedout() - size),
                    'capacity': size + max(pool._max_overflow, 0)})
    return out


def _is_memory_sqlite(url: str) -> bool:
    rest = url.split('://', 1)[-1]
    return rest in ('', '/', '/:memory:') or ':memory:' in rest or 'mode=memory' in rest


def create_db_engine(settings, url: str | None = None):
    """
    Build the SQLAlchemy engine from ``db.*`` without touching the schema.
    Used by :func:`init_db` and by ``python -m sajha.db``.

    Supports:
      - SQLite (default, zero-config, WAL mode)
      - PostgreSQL via psycopg2 or psycopg (v3); sessions run in UTC
    """
    url = url or settings.database_url
    db_type = 'postgresql' if url.startswith('postgresql') else 'sqlite' if url.startswith('sqlite') \
        else settings.db_type

    opts = pool_options(settings)
    if db_type == 'sqlite':
        # A file database shared by the request threads: a QueuePool (one connection per thread
        # at a time, reused), check_same_thread off because a connection moves between pool
        # threads. timeout / busy_timeout: wait for a lock another process holds (several workers
        # starting on one file, a writer in another worker). An in-memory database keeps
        # SQLAlchemy's own pool (one database per connection otherwise).
        kwargs: Dict[str, Any] = {}
        if not _is_memory_sqlite(url):
            kwargs = {'poolclass': CountingQueuePool, **opts}
        engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 30},
                               echo=settings.db_echo, **kwargs)

        # Enable WAL mode for better concurrent read performance.  WAL is stored in the file,
        # so only the first connection switches it; switching needs an exclusive lock, and
        # asking again on every connection failed with "database is locked" while another
        # worker was creating the schema.
        @event.listens_for(engine, 'connect')
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute('PRAGMA busy_timeout=30000')
            mode = (cursor.execute('PRAGMA journal_mode').fetchone() or [''])[0]
            if str(mode).lower() not in ('wal', 'memory'):
                cursor.execute('PRAGMA journal_mode=WAL')
            # WAL with synchronous=NORMAL: durable against a process crash, and a commit no longer
            # waits for an fsync (a power loss can lose the last transactions, never corrupt the file)
            cursor.execute('PRAGMA synchronous=NORMAL')
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()

        logger.info(f'Database: SQLite at {url.split("///", 1)[-1]} (pool {opts["pool_size"]}+'
                    f'{opts["max_overflow"]}, checkout timeout {opts["pool_timeout"]:g} s)')
        return engine

    if db_type != 'postgresql':
        raise ValueError(
            f'Unsupported db.type: {settings.db_type}. '
            f'Use "sqlite" or "postgresql" in application.yml.'
        )

    # Detect available driver
    driver = settings.db_driver or 'psycopg2'
    _driver_available = False

    if driver == 'psycopg2':
        try:
            import psycopg2  # noqa: F401
            _driver_available = True
        except ImportError:
            logger.warning('psycopg2 not installed, trying psycopg (v3)...')
            driver = 'psycopg'

    if driver == 'psycopg' and not _driver_available:
        try:
            import psycopg  # noqa: F401
            _driver_available = True
        except ImportError as e:
            logger.debug(f"Handled: {e}")

    if not _driver_available:
        raise ImportError(
            'No PostgreSQL driver found. Install one of:\n'
            '  pip install psycopg2-binary    # (recommended, C-based)\n'
            '  pip install "psycopg[binary]"  # (psycopg v3, pure Python fallback)\n'
        )

    # Rebuild URL with detected driver if it differs from config
    if driver != settings.db_driver and not settings.db_url and url == settings.database_url:
        from urllib.parse import quote_plus
        password = quote_plus(settings.db_password)
        url = (
            f'postgresql+{driver}://'
            f'{settings.db_user}:{password}@'
            f'{settings.db_host}:{settings.db_port}/'
            f'{settings.db_name}'
        )

    engine = create_engine(
        url,
        poolclass=CountingQueuePool,
        **opts,
        pool_pre_ping=True,
        echo=settings.db_echo,
        # TIMESTAMPTZ columns: naive datetimes written by SAJHA are UTC, values read back are UTC.
        connect_args={'options': '-c timezone=UTC'},
    )

    # Validate connection
    where = f'{engine.url.host}:{engine.url.port or 5432}/{engine.url.database}'
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        logger.info(f'Database: PostgreSQL at {where} (driver={driver}, pool {opts["pool_size"]}+{opts["max_overflow"]}, '
                    f'checkout timeout {opts["pool_timeout"]:g} s)')
    except Exception as e:
        raise RuntimeError(
            f'Cannot connect to PostgreSQL at {where}: {e}\n'
            f'Check db.host, db.port, db.name, db.user, db.password in application.yml'
        ) from e
    return engine


def init_db(settings) -> None:
    """
    Initialize the database engine and create (SQLite) or verify (PostgreSQL) the schema.
    Called once at application startup.  There are no migrations.

    SQLite (development): db/scripts/sqlite/schema.sql is run here (seed.sql too on a new
    database).  PostgreSQL (production): SAJHA runs no DDL.  The tables and columns the code
    uses are checked; anything missing stops start-up (db.schema_check: strict, the default)
    or logs a warning (warn).  See docs/getting-started/Database Setup.md.
    """
    global _engine, _SessionLocal

    _engine = create_db_engine(settings)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    from sajha.db import schema
    root = schema.scripts_root(settings.db_scripts_dir)
    if _engine.dialect.name == 'sqlite':
        schema.create_sqlite(_engine, root)
    schema.check(_engine, getattr(settings, 'db_schema_check', 'strict'), root, notify=True)

    logger.info('Database initialization complete')


def get_engine():
    """Return the SQLAlchemy engine."""
    if _engine is None:
        raise RuntimeError('Database not initialized. Call init_db() first.')
    return _engine


def get_db() -> Session:
    """
    FastAPI dependency — yields a DB session per request.

    Usage:
        @router.get('/items')
        def list_items(db: Session = Depends(get_db)):
            ...
    """
    if _SessionLocal is None:
        raise RuntimeError('Database not initialized. Call init_db() first.')
    db = _SessionLocal()
    try:
        yield db
    except BaseException:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()


@contextmanager
def session_scope(commit: bool = False) -> Iterator[Session]:
    """One unit of database work: a session that is always closed (its connection back in the
    pool) when the block ends, rolled back when it raises, committed at the end when ``commit``.
    Use it in services, tools and background jobs instead of ``get_db_session()`` + ``close``::

        with session_scope() as db:
            rows = SomeDAO(db).list()
        slow_work(rows)          # no connection held here
    """
    db = get_db_session()
    try:
        yield db
        if commit:
            db.commit()
    except BaseException:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()


def release_session(db) -> None:
    """Give a request's database session's connection back to the pool now, before the request
    awaits long work (a tool call, a model call, a federated call, an open stream).

    A session holds its pool connection from its first query until it is closed, and the request's
    session (:func:`get_db`) is closed only when the response has been sent.  A request that read the
    database (authentication, a lookup) and then waited on a slow call kept a connection the whole
    time: enough of them in flight emptied the pool, and the next request blocked on it (on the event
    loop, for an async route) for up to the pool timeout.  ``Session.close`` releases the connection;
    the session stays usable (the next query checks a connection out again, and :func:`get_db` closes
    it at the end as before).  Objects it loaded are detached: attributes already loaded still read,
    lazy loads raise.  docs/architecture/Scaling and State.md §7.
    """
    if db is None:
        return
    try:
        db.close()
    except Exception as e:
        logger.debug(f'release_session: {e}')


def get_db_session() -> Session:
    """
    Imperative session for use outside of FastAPI dependency injection
    (background tasks, seed scripts, startup logic).
    Caller is responsible for closing.
    """
    if _SessionLocal is None:
        raise RuntimeError('Database not initialized. Call init_db() first.')
    return _SessionLocal()
