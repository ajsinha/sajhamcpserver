# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""A PostgreSQL schema built from db/scripts/postgresql/schema.sql (+ seed.sql) for the tests that run
on a real server when SAJHA_TEST_PG_URL names a disposable database (tests/test_postgresql.py, the
``database_pg`` backend of tests/test_state_store.py). Without it those tests skip.

Each test process gets its own PostgreSQL schema (``sajha_t_<hex>``), created and filled the way an
operator does it (the two files, run as they are) and dropped at exit, so the tests neither need an
empty database nor disturb the other PostgreSQL tests (tests/test_db_schema.py drops ``public`` of
SAJHA_TEST_POSTGRES_URL). The engine's sessions use that schema (``search_path``) and run in UTC, like
SAJHA's own engine (sajha/db/engine.py). docs/getting-started/Database Setup.md.
"""

from __future__ import annotations

import atexit
import os
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PG_URL = os.environ.get('SAJHA_TEST_PG_URL', '')
_engine = None


def pg_engine():
    """The shared engine on this process's schema (built on first use); None without SAJHA_TEST_PG_URL."""
    global _engine
    if not PG_URL:
        return None
    if _engine is None:
        from sqlalchemy import create_engine
        name = f'sajha_t_{uuid.uuid4().hex[:10]}'
        admin = create_engine(PG_URL)
        with admin.begin() as c:
            c.exec_driver_sql(f'CREATE SCHEMA {name}')
        admin.dispose()
        eng = create_engine(PG_URL, pool_pre_ping=True,
                            connect_args={'options': f'-c search_path={name} -c timezone=UTC'})
        with eng.begin() as c:
            c.exec_driver_sql((ROOT / 'db/scripts/postgresql/schema.sql').read_text(encoding='utf-8'))
            c.exec_driver_sql((ROOT / 'db/scripts/postgresql/seed.sql').read_text(encoding='utf-8'))

        def _drop():
            eng.dispose()
            a = create_engine(PG_URL)
            try:
                with a.begin() as c:
                    c.exec_driver_sql(f'DROP SCHEMA IF EXISTS {name} CASCADE')
            finally:
                a.dispose()
        atexit.register(_drop)
        _engine = eng
    return _engine
