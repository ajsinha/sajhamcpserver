# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""SAJHA MCP Server v3 — Test Configuration"""
import os, sys
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(str(Path(__file__).parent.parent))

# Tests never write tracked repository files. The duckdb tools open
# <data.duckdb.dir>/duckdb_analytics.db (DuckDB rewrites it and drops its .wal on
# checkpoint), so point them at a per-session temp copy of data/duckdb.
import atexit, shutil, tempfile
_DUCKDB_TMP = Path(tempfile.mkdtemp(prefix='sajha-test-duckdb-'))
shutil.copytree(Path('data/duckdb'), _DUCKDB_TMP / 'duckdb', dirs_exist_ok=True)
os.environ['data.duckdb.dir'] = str(_DUCKDB_TMP / 'duckdb')       # tool-config ${data.duckdb.dir}
os.environ['SAJHA_DATA_DUCKDB_DIR'] = str(_DUCKDB_TMP / 'duckdb')  # sajha.core.config
atexit.register(shutil.rmtree, _DUCKDB_TMP, True)
# The document index (ai.rag) builds on first search and is not persisted under data/.
os.environ.setdefault('SAJHA_AI_RAG_BUILD_ON_START', 'false')
os.environ.setdefault('SAJHA_AI_RAG_PERSIST', 'false')
# Periodic snapshots (snapshots.*) write under data/; tests that need them build their own.
os.environ.setdefault('SAJHA_SNAPSHOTS_ENABLED', 'false')
# The administrators' credential files: tests never read the developer's real config/users.json,
# config/apikeys.json or write config/apikeys_db.json; the test admin switch is off unless a test turns it on.
os.environ.setdefault('SAJHA_AUTH_USERS_FILE_PATH', str(_DUCKDB_TMP / 'users.json'))
os.environ.setdefault('SAJHA_AUTH_API_KEYS_DB_DUMP_PATH', str(_DUCKDB_TMP / 'apikeys_db.json'))
os.environ.setdefault('SAJHA_CONFIG_APIKEYS_PATH', str(_DUCKDB_TMP / 'apikeys.json'))
os.environ.setdefault('SAJHA_SAJHANET_TEST_ADMIN_KEY_ENABLED', 'false')
# Tests create SAJHA Net CAs explicitly; the automatic CA of a net of one is tested on its own.
os.environ.setdefault('SAJHA_SAJHANET_CA_AUTO_INIT', 'false')
# The suite exercises the CA through the shipped config; open mode (the shipped admission) has its own tests.
os.environ.setdefault('SAJHA_SAJHANET_PLUGINS_ADMISSION', 'builtin_ca')


import pytest


@pytest.fixture(autouse=True)
def _keep_the_database_engine():
    """Safety net for test order: a test that clears or re-points the process-wide database
    engine (sajha.db.engine._engine/_SessionLocal) must not leave an app started earlier
    (the session ``web`` fixture) without its database. When an engine was set before the
    test, it is put back afterwards; an engine the test made in its place is disposed."""
    from sajha.db import engine as eng
    saved = eng._engine, eng._SessionLocal
    yield
    if saved[0] is None or (eng._engine, eng._SessionLocal) == saved:
        return
    if eng._engine is not None and eng._engine is not saved[0]:
        eng._engine.dispose()
    eng._engine, eng._SessionLocal = saved


@pytest.fixture(scope='session')
def web():
    """(TestClient, admin cookies) on one started app, shared by the help tests.

    The client's own cookie jar is cleared after signing in, so a plain ``c.get`` is an
    anonymous request and ``c.get(url, cookies=admin)`` a signed-in one."""
    from fastapi.testclient import TestClient
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        r = c.post('/login', data={'user_id': 'admin', 'password': 'admin123'}, follow_redirects=False)
        admin = dict(r.cookies)
        c.cookies.clear()
        yield c, admin
