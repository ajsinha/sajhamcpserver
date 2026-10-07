"""The start-up schema check prints the SQL to run, and ``python -m sajha.db upgrade-sql``
prints the DDL that brings a database up to its dialect's schema file (Roadmap N2, X17).

SAJHA never runs these statements: on PostgreSQL an operator does; on SQLite SAJHA only
creates missing tables from schema.sql and never alters an existing one. Set
SAJHA_TEST_POSTGRES_URL (an empty database SAJHA may create tables in) to run the
PostgreSQL case against a real server.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from sajha.db import schema

ROOT = Path(__file__).resolve().parent.parent
PG_URL = os.environ.get('SAJHA_TEST_POSTGRES_URL', '')


def _full_sqlite(path: Path):
    e = create_engine(f'sqlite:///{path}')
    schema.run_script(e, schema.schema_file('sqlite'))
    return e


def _drop_some(e):
    with e.begin() as c:
        c.exec_driver_sql('DROP TABLE quality_runs')
        c.exec_driver_sql('DROP INDEX ix_session_user')
        c.exec_driver_sql('ALTER TABLE users DROP COLUMN must_change_password')


def test_the_schema_file_is_parsed_into_tables_columns_and_indexes():
    for dialect in schema.DIALECTS:
        sf = schema.parse_schema_file(dialect)
        assert set(sf.tables) == set(schema.tables())
        for name, t in schema.tables().items():
            assert list(sf.tables[name].columns) == [c.name for c in t.columns], name
        assert sf.indexes['ix_users_user_id'].table == 'users'
        assert sf.indexes['ix_users_user_id'].statement.startswith('CREATE UNIQUE INDEX IF NOT EXISTS')
        assert sf.tables['users'].statement.startswith('CREATE TABLE IF NOT EXISTS users (')


def test_a_complete_database_needs_nothing(tmp_path):
    assert schema.upgrade_statements(_full_sqlite(tmp_path / 'full.db')) == []


def test_statements_for_missing_table_column_and_index(tmp_path):
    e = _full_sqlite(tmp_path / 'old.db')
    _drop_some(e)
    stmts = schema.upgrade_statements(e)
    assert 'ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0;' in stmts
    assert 'CREATE INDEX IF NOT EXISTS ix_session_user ON user_sessions (user_id);' in stmts
    assert any(s.startswith('CREATE TABLE IF NOT EXISTS quality_runs (') for s in stmts)
    assert 'CREATE INDEX IF NOT EXISTS ix_quality_runs_kind_started ON quality_runs (kind, started_at);' in stmts
    # printing changed nothing
    assert 'quality_runs' not in inspect(e).get_table_names()
    # and the printed SQL, run by the operator, completes the database
    with e.begin() as c:
        for s in stmts:
            c.exec_driver_sql(s)
    assert schema.missing(e) == {} and schema.upgrade_statements(e) == []


def test_postgresql_add_column_uses_if_not_exists_and_sqlite_flags_what_it_cannot_add():
    assert schema.add_column_sql('postgresql', 'users', 'x BOOLEAN NOT NULL DEFAULT FALSE') == \
        'ALTER TABLE users ADD COLUMN IF NOT EXISTS x BOOLEAN NOT NULL DEFAULT FALSE;'
    assert schema.add_column_sql('sqlite', 'users', 'x INTEGER') == 'ALTER TABLE users ADD COLUMN x INTEGER;'
    for bad in ('t TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP', 'x VARCHAR(5) NOT NULL',
                'id VARCHAR(36) NOT NULL PRIMARY KEY'):
        out = schema.add_column_sql('sqlite', 'users', bad)
        assert out.startswith('-- SQLite cannot add') and out.endswith(f'ALTER TABLE users ADD COLUMN {bad};')


def test_not_ready_message_prints_the_sql_on_sqlite(tmp_path):
    e = _full_sqlite(tmp_path / 'old.db')
    _drop_some(e)
    miss = schema.missing(e)
    msg = schema.not_ready_message(e, miss)
    assert 'missing columns in users: must_change_password' in msg
    assert '    ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0;' in msg
    assert 'python -m sajha.db upgrade-sql' in msg
    with pytest.raises(schema.SchemaNotReady, match='ALTER TABLE users ADD COLUMN'):
        schema.check(e, 'strict')


def test_missing_index_only_warns_with_the_statement(tmp_path, caplog):
    e = _full_sqlite(tmp_path / 'ix.db')
    with e.begin() as c:
        c.exec_driver_sql('DROP INDEX ix_session_user')
    with caplog.at_level('WARNING'):
        assert schema.check(e, 'strict') == {}
    assert 'CREATE INDEX IF NOT EXISTS ix_session_user ON user_sessions (user_id);' in caplog.text


def test_create_sqlite_on_an_older_database_still_creates_missing_tables(tmp_path):
    """An index on a column an old table lacks fails the whole script; the retry statement by
    statement still creates the missing tables, and the check names the column with its SQL."""
    e = _full_sqlite(tmp_path / 'older.db')
    with e.begin() as c:
        c.exec_driver_sql('DROP TABLE quality_runs')
        c.exec_driver_sql('DROP INDEX ix_session_user')
        c.exec_driver_sql('ALTER TABLE user_sessions DROP COLUMN user_id')
    assert schema.create_sqlite(e) is False
    assert 'quality_runs' in inspect(e).get_table_names()
    msg = schema.not_ready_message(e, schema.missing(e))
    assert 'ALTER TABLE user_sessions ADD COLUMN user_id' in msg


def test_cli_upgrade_sql_and_sql_missing(tmp_path, capsys):
    from sajha.db.__main__ import main
    full = tmp_path / 'full.db'
    _full_sqlite(full)
    assert main(['upgrade-sql', '--url', f'sqlite:///{full}']) == 0
    assert 'nothing to do' in capsys.readouterr().out
    old = tmp_path / 'old.db'
    _drop_some(_full_sqlite(old))
    assert main(['upgrade-sql', '--url', f'sqlite:///{old}']) == 3
    out = capsys.readouterr().out
    assert 'SAJHA never runs these statements' in out
    assert 'ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0;' in out
    assert main(['sql', '--missing', '--url', f'sqlite:///{old}']) == 3
    assert capsys.readouterr().out == out
    assert 'quality_runs' not in inspect(create_engine(f'sqlite:///{old}')).get_table_names()


@pytest.mark.skipif(not PG_URL, reason='set SAJHA_TEST_POSTGRES_URL to an empty PostgreSQL database')
def test_postgresql_upgrade_sql_against_a_real_server():
    engine = create_engine(PG_URL)
    with engine.begin() as c:
        c.exec_driver_sql('DROP SCHEMA public CASCADE')
        c.exec_driver_sql('CREATE SCHEMA public')
    pg_file = ROOT / 'db/scripts/postgresql/schema.sql'
    with engine.begin() as c:
        c.exec_driver_sql(pg_file.read_text(encoding='utf-8'))
    assert schema.upgrade_statements(engine) == []
    with engine.begin() as c:
        c.exec_driver_sql('DROP TABLE quality_runs')
        c.exec_driver_sql('DROP INDEX ix_session_user')
        c.exec_driver_sql('ALTER TABLE users DROP COLUMN must_change_password')
    stmts = schema.upgrade_statements(engine)
    assert 'ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;' in stmts
    assert 'CREATE INDEX IF NOT EXISTS ix_session_user ON user_sessions (user_id);' in stmts
    msg = schema.not_ready_message(engine, schema.missing(engine))
    assert 'ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password' in msg
    assert 'quality_runs' not in inspect(engine).get_table_names()      # printing ran nothing
    with engine.begin() as c:
        for s in stmts:
            c.exec_driver_sql(s)
    assert schema.missing(engine) == {} and schema.upgrade_statements(engine) == []
