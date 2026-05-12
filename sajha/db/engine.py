"""
SAJHA MCP Server v3 — Database Engine & Session Factory
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

Supports SQLite (default, zero-config) and PostgreSQL (production).
Configured via db.type in application.yml or SAJHA_DB_TYPE env var.
"""

import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sajha.db.base import Base

logger = logging.getLogger(__name__)

# Module-level singletons — initialized by init_db()
_engine = None
_SessionLocal: sessionmaker = None


def init_db(settings) -> None:
    """
    Initialize the database engine and create all tables.
    Called once at application startup.

    Supports:
      - SQLite (default, zero-config, WAL mode)
      - PostgreSQL via psycopg2 or psycopg (v3)
    """
    global _engine, _SessionLocal

    url = settings.database_url
    connect_args = {}

    if settings.db_type == 'sqlite':
        connect_args = {'check_same_thread': False}
        _engine = create_engine(
            url,
            connect_args=connect_args,
            echo=settings.db_echo,
        )
        # Enable WAL mode for better concurrent read performance
        @event.listens_for(_engine, 'connect')
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()

        logger.info(f'Database initialized: SQLite at {settings.db_path}')

    elif settings.db_type == 'postgresql':
        # Detect available driver
        driver = settings.db_driver or 'psycopg2'
        _driver_available = False

        if driver == 'psycopg2':
            try:
                import psycopg2  # noqa: F401
                _driver_available = True
            except ImportError:
                logger.warning('psycopg2 not installed, trying psycopg (v3)...', exc_info=True)
                driver = 'psycopg'

        if driver == 'psycopg' and not _driver_available:
            try:
                import psycopg  # noqa: F401
                _driver_available = True
            except ImportError as e:
                logger.debug(f"Handled: {e}")
                pass

        if not _driver_available:
            raise ImportError(
                'No PostgreSQL driver found. Install one of:\n'
                '  pip install psycopg2-binary    # (recommended, C-based)\n'
                '  pip install "psycopg[binary]"  # (psycopg v3, pure Python fallback)\n'
            )

        # Rebuild URL with detected driver if it differs from config
        if driver != settings.db_driver and not settings.db_url:
            from urllib.parse import quote_plus
            password = quote_plus(settings.db_password)
            url = (
                f'postgresql+{driver}://'
                f'{settings.db_user}:{password}@'
                f'{settings.db_host}:{settings.db_port}/'
                f'{settings.db_name}'
            )

        _engine = create_engine(
            url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_pool_size,
            pool_pre_ping=True,
            echo=settings.db_echo,
        )

        # Validate connection
        try:
            with _engine.connect() as conn:
                conn.execute(text('SELECT 1'))
            logger.info(
                f'Database initialized: PostgreSQL at '
                f'{settings.db_host}:{settings.db_port}/{settings.db_name} '
                f'(driver={driver}, pool_size={settings.db_pool_size})'
            )
        except Exception as e:
            raise RuntimeError(
                f'Cannot connect to PostgreSQL at '
                f'{settings.db_host}:{settings.db_port}/{settings.db_name}: {e}\n'
                f'Check db.host, db.port, db.name, db.user, db.password in application.yml'
            ) from e

    else:
        raise ValueError(
            f'Unsupported db.type: {settings.db_type}. '
            f'Use "sqlite" or "postgresql" in application.yml.'
        )

    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    # Import models for ORM mapping (models map to tables created by SQL scripts)
    import sajha.db.models  # noqa: F401

    # Run SQL scripts to create schema and seed data
    _run_sql_scripts(settings)

    logger.info('Database initialization complete')


def _run_sql_scripts(settings) -> None:
    """
    Execute SQL scripts from db/scripts/ directory in sorted order.
    Scripts are idempotent (IF NOT EXISTS / WHERE NOT EXISTS).

    Expected scripts:
        001_schema.sql  — Table definitions (DDL)
        002_seed.sql    — Default roles, permissions, admin user
    """
    from pathlib import Path

    scripts_dir = Path(settings.db_scripts_dir)
    if not scripts_dir.is_absolute():
        scripts_dir = Path.cwd() / scripts_dir

    if not scripts_dir.is_dir():
        logger.warning(f'SQL scripts directory not found: {scripts_dir}')
        logger.info('Falling back to SQLAlchemy metadata.create_all()')
        Base.metadata.create_all(bind=_engine)
        return

    sql_files = sorted(scripts_dir.glob('*.sql'))
    if not sql_files:
        logger.warning(f'No SQL scripts found in {scripts_dir}')
        Base.metadata.create_all(bind=_engine)
        return

    with _engine.connect() as conn:
        for sql_file in sql_files:
            logger.info(f'  Executing: {sql_file.name}')
            sql = sql_file.read_text(encoding='utf-8')

            # Split on semicolons and execute each statement
            # (handles multi-statement SQL files)
            statements = [s.strip() for s in sql.split(';') if s.strip()]
            executed = 0
            for stmt in statements:
                # Skip pure comments
                lines = [l for l in stmt.split('\n') if l.strip() and not l.strip().startswith('--')]
                if not lines:
                    continue
                try:
                    conn.execute(text(stmt))
                    executed += 1
                except Exception as e:
                    # Log but don't fail — scripts are idempotent
                    logger.debug(f'    Statement skipped: {e}')

            conn.commit()
            logger.info(f'    → {executed} statements executed from {sql_file.name}')


def get_engine():
    """Return the SQLAlchemy engine (for Alembic or direct use)."""
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
