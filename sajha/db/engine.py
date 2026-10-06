"""
SAJHA MCP Server v3 — Database Engine & Session Factory
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Supports SQLite (default, zero-config) and PostgreSQL (production).
Configured via db.type in application.yml or SAJHA_DB_TYPE env var.
"""

import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

# Module-level singletons — initialized by init_db()
_engine = None
_SessionLocal: sessionmaker = None


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

    if db_type == 'sqlite':
        engine = create_engine(url, connect_args={'check_same_thread': False}, echo=settings.db_echo)

        # Enable WAL mode for better concurrent read performance
        @event.listens_for(engine, 'connect')
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()

        logger.info(f'Database: SQLite at {url.split("///", 1)[-1]}')
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
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_pool_size,
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
        logger.info(f'Database: PostgreSQL at {where} (driver={driver}, pool_size={settings.db_pool_size})')
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
    schema.check(_engine, getattr(settings, 'db_schema_check', 'strict'), root)

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
    finally:
        db.close()


def get_db_session() -> Session:
    """
    Imperative session for use outside of FastAPI dependency injection
    (background tasks, seed scripts, startup logic).
    Caller is responsible for closing.
    """
    if _SessionLocal is None:
        raise RuntimeError('Database not initialized. Call init_db() first.')
    return _SessionLocal()
