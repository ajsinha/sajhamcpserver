"""
The schema files and the code agree: db/scripts/sqlite/schema.sql, db/scripts/postgresql/schema.sql
and every SQLAlchemy MetaData in SAJHA (sajha.db.schema.metadatas()) describe the same tables,
columns, types, nullability, primary keys, foreign keys, unique keys and indexes.

There are no migrations: SQLite runs its schema file at start-up, PostgreSQL gets its file from
an operator (psql -f) and SAJHA only checks it.  Set SAJHA_TEST_POSTGRES_URL (an empty database
SAJHA may create tables in, e.g. postgresql+psycopg2://u:p@localhost:5432/sajha_schema_test) to
apply the PostgreSQL file to a real server and compare the reflected result too.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, Text, create_engine, inspect

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

from sajha.db import schema  # noqa: E402

PG_FILE = ROOT / 'db/scripts/postgresql/schema.sql'
SQLITE_FILE = ROOT / 'db/scripts/sqlite/schema.sql'

#: Tables whose DateTime columns are naive UTC in the code (TIMESTAMP on PostgreSQL);
#: every other DateTime column is TIMESTAMPTZ there.
NAIVE_TIMESTAMP_TABLES = {'connected_accounts'}


# ── the code's view ──────────────────────────────────────────────

def _family(t) -> str:
    """Normalised type of a SQLAlchemy column type (variants resolved by the caller)."""
    if isinstance(t, Boolean):
        return 'boolean'
    if isinstance(t, DateTime):
        return 'timestamp'
    if isinstance(t, Float):
        return 'float'
    if isinstance(t, BigInteger):
        return 'bigint'
    if isinstance(t, Integer):
        return 'integer'
    if isinstance(t, Text):
        return 'text'
    if isinstance(t, String):
        return f'varchar({t.length})' if t.length else 'text'
    raise AssertionError(f'unmapped type {t!r}')


def _resolve(col, dialect: str):
    t = col.type
    return t._variant_mapping.get(dialect, t) if hasattr(t, '_variant_mapping') else t


def expected(dialect: str) -> dict:
    """``{table: {...}}`` from the code, with types as the dialect's file must spell them."""
    out = {}
    for name, t in schema.tables().items():
        cols = {}
        for c in t.columns:
            fam = _family(_resolve(c, dialect))
            if dialect == 'postgresql':
                if fam == 'timestamp' and name not in NAIVE_TIMESTAMP_TABLES:
                    fam = 'timestamptz'
            cols[c.name] = {'type': fam, 'nullable': bool(c.nullable) and not c.primary_key}
        uniques = {tuple(c.name for c in u.columns) for u in t.constraints
                   if u.__class__.__name__ == 'UniqueConstraint'}
        for c in t.columns:
            if c.unique and not c.index:
                uniques.add((c.name,))
        indexes = {i.name: (tuple(c.name for c in i.columns), bool(i.unique)) for i in t.indexes}
        fks = {(tuple(e.parent.name for e in fk.elements), fk.elements[0].column.table.name,
                tuple(e.column.name for e in fk.elements), (fk.ondelete or '').upper() or None)
               for fk in t.foreign_key_constraints}
        out[name] = {'columns': cols, 'pk': tuple(c.name for c in t.primary_key.columns),
                     'uniques': uniques, 'indexes': indexes, 'fks': fks,
                     'autoinc': {c.name for c in t.primary_key.columns if c.autoincrement is True}}
    return out


# ── a parser for our own schema files (CREATE TABLE / CREATE INDEX, nothing else) ──

_TYPE_RE = re.compile(r'^(DOUBLE PRECISION|VARCHAR\(\d+\)|[A-Z]+)', re.I)


def _split_top(body: str):
    parts, depth, buf = [], 0, []
    for ch in body:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    parts.append(''.join(buf).strip())
    return [p for p in parts if p]


def _cols(s: str):
    return tuple(c.strip() for c in s.split(','))


def _norm_type(raw: str, dialect: str) -> str:
    r = raw.upper()
    m = re.match(r'VARCHAR\((\d+)\)', r)
    if m:
        return f'varchar({m.group(1)})'
    table = {'postgresql': {'TEXT': 'text', 'INTEGER': 'integer', 'BIGINT': 'bigint', 'BOOLEAN': 'boolean',
                            'TIMESTAMPTZ': 'timestamptz', 'TIMESTAMP': 'timestamp',
                            'DOUBLE PRECISION': 'float'},
             'sqlite': {'TEXT': 'text', 'INTEGER': 'integer', 'BIGINT': 'bigint', 'BOOLEAN': 'boolean',
                        'TIMESTAMP': 'timestamp',
                        'REAL': 'float'}}[dialect]
    assert r in table, f'{dialect} schema file: type {raw} is not one this dialect should use'
    return table[r]


def parse_schema(path: Path, dialect: str) -> dict:
    sql = path.read_text(encoding='utf-8')
    out = {}
    for stmt in schema.split_statements(sql):
        s = ' '.join(stmt.split())
        m = re.match(r'CREATE TABLE IF NOT EXISTS (\w+) \((.*)\)$', s, re.I)
        if m:
            name, body = m.group(1), m.group(2)
            assert name not in out, f'{path.name}: table {name} is created twice'
            t = out.setdefault(name, {'columns': {}, 'pk': (), 'uniques': set(), 'indexes': {}, 'fks': set(),
                                      'autoinc': set()})
            for part in _split_top(body):
                pm = re.match(r'PRIMARY KEY \(([^)]*)\)$', part, re.I)
                um = re.match(r'UNIQUE \(([^)]*)\)$', part, re.I)
                if pm:
                    t['pk'] = _cols(pm.group(1))
                    continue
                if um:
                    t['uniques'].add(_cols(um.group(1)))
                    continue
                cm = re.match(r'(\w+) (.*)$', part)
                col, rest = cm.group(1), cm.group(2)
                tm = _TYPE_RE.match(rest)
                typ = _norm_type(tm.group(1), dialect)
                rest_u = rest.upper()
                is_pk = 'PRIMARY KEY' in rest_u
                if is_pk:
                    t['pk'] = (col,)
                if 'GENERATED BY DEFAULT AS IDENTITY' in rest_u or (dialect == 'sqlite' and is_pk
                                                                     and typ == 'integer'):
                    t['autoinc'].add(col)
                if re.search(r'\bUNIQUE\b', rest_u):
                    t['uniques'].add((col,))
                fm = re.search(r'REFERENCES (\w+) \((\w+)\)(?: ON DELETE (CASCADE|SET NULL|RESTRICT))?', rest, re.I)
                if fm:
                    t['fks'].add(((col,), fm.group(1), (fm.group(2),), (fm.group(3) or '').upper() or None))
                t['columns'][col] = {'type': typ, 'nullable': not ('NOT NULL' in rest_u or is_pk)}
            continue
        m = re.match(r'CREATE (UNIQUE )?INDEX IF NOT EXISTS (\w+) ON (\w+) \(([^)]*)\)$', s, re.I)
        if m:
            out[m.group(3)]['indexes'][m.group(2)] = (_cols(m.group(4)), bool(m.group(1)))
            continue
        raise AssertionError(f'{path.name}: unexpected statement (only CREATE TABLE / CREATE INDEX): {s[:120]}')
    return out


def _compare(got: dict, want: dict, where: str):
    assert set(got) == set(want), (f'{where}: tables differ. only in file: {sorted(set(got) - set(want))}; '
                                   f'only in code: {sorted(set(want) - set(got))}')
    for name in want:
        g, w = got[name], want[name]
        assert list(g['columns']) == list(w['columns']), f'{where}: {name} columns (or their order) differ'
        for col, spec in w['columns'].items():
            assert g['columns'][col] == spec, f'{where}: {name}.{col} is {g["columns"][col]}, code says {spec}'
        for key in ('pk', 'uniques', 'indexes', 'fks', 'autoinc'):
            assert g[key] == w[key], f'{where}: {name} {key}: file {g[key]} != code {w[key]}'


# ── (b) the PostgreSQL file against the code ─────────────────────

def test_postgresql_file_matches_the_code():
    _compare(parse_schema(PG_FILE, 'postgresql'), expected('postgresql'), 'postgresql/schema.sql')


def test_sqlite_file_text_matches_the_code():
    _compare(parse_schema(SQLITE_FILE, 'sqlite'), expected('sqlite'), 'sqlite/schema.sql (parsed)')


def test_the_two_files_describe_the_same_schema():
    pg, lite = parse_schema(PG_FILE, 'postgresql'), parse_schema(SQLITE_FILE, 'sqlite')
    assert list(pg) == list(lite), 'tables must appear in the same order in both files'
    for name in pg:
        assert list(pg[name]['columns']) == list(lite[name]['columns'])
        for key in ('pk', 'uniques', 'indexes', 'fks', 'autoinc'):
            assert pg[name][key] == lite[name][key], (name, key)


def test_files_are_idempotent_and_hold_no_migration_machinery():
    for f in (PG_FILE, SQLITE_FILE):
        text = f.read_text(encoding='utf-8')
        assert 'schema_version' not in text and 'ALTER TABLE' not in text.upper()
        for stmt in schema.split_statements(text):
            assert 'IF NOT EXISTS' in stmt.upper(), stmt[:80]
    assert sorted(p.name for p in (ROOT / 'db/scripts/postgresql').iterdir()) == ['schema.sql', 'seed.sql']
    assert sorted(p.name for p in (ROOT / 'db/scripts/sqlite').iterdir()) == ['schema.sql', 'seed.sql']
    assert not (ROOT / 'sajha/db/migrations.py').exists()


# ── (a) SQLite built from its file, reflected, against the code ──

def _reflect(engine) -> dict:
    insp = inspect(engine)
    out = {}
    dialect = engine.dialect.name
    for name in insp.get_table_names():
        cols = {}
        for c in insp.get_columns(name):
            t = c['type']
            if dialect == 'postgresql' and isinstance(t, DateTime):
                fam = 'timestamptz' if getattr(t, 'timezone', False) else 'timestamp'
            else:
                fam = _family(t)
            cols[c['name']] = {'type': fam, 'nullable': bool(c['nullable'])}
        pk = tuple(insp.get_pk_constraint(name)['constrained_columns'])
        idx = {i['name']: (tuple(i['column_names']), bool(i['unique'])) for i in insp.get_indexes(name)
               if not i.get('duplicates_constraint')}   # PostgreSQL lists UNIQUE constraints' indexes too
        if dialect == 'sqlite':          # SQLAlchemy misses inline column UNIQUE; ask SQLite
            with engine.connect() as conn:
                uniques = {tuple(r[2] for r in conn.exec_driver_sql(f'PRAGMA index_info("{ix[1]}")'))
                           for ix in conn.exec_driver_sql(f'PRAGMA index_list({name})').fetchall()
                           if ix[3] == 'u'}
        else:
            uniques = {tuple(u['column_names']) for u in insp.get_unique_constraints(name)}
        if dialect == 'sqlite':          # SQLAlchemy drops ON DELETE of inline REFERENCES; ask SQLite
            with engine.connect() as conn:
                rows = conn.exec_driver_sql(f'PRAGMA foreign_key_list({name})').fetchall()
            fks = {((r[3],), r[2], (r[4],), None if r[6] == 'NO ACTION' else r[6]) for r in rows}
        else:
            fks = {(tuple(f['constrained_columns']), f['referred_table'], tuple(f['referred_columns']),
                    ((f.get('options') or {}).get('ondelete') or '').upper() or None)
                   for f in insp.get_foreign_keys(name)}
        out[name] = {'columns': cols, 'pk': pk, 'uniques': uniques, 'indexes': idx, 'fks': fks}
    return out


def _compare_reflected(got: dict, want: dict, where: str):
    assert set(got) == set(want), (f'{where}: tables differ. only in database: {sorted(set(got) - set(want))}; '
                                   f'only in code: {sorted(set(want) - set(got))}')
    for name, w in want.items():
        g = got[name]
        assert list(g['columns']) == list(w['columns']), f'{where}: {name} columns differ'
        for col, spec in w['columns'].items():
            assert g['columns'][col] == spec, f'{where}: {name}.{col} is {g["columns"][col]}, code says {spec}'
        for key in ('pk', 'uniques', 'indexes', 'fks'):
            assert g[key] == w[key], f'{where}: {name} {key}: database {g[key]} != code {w[key]}'


def test_sqlite_built_from_its_file_matches_the_code(tmp_path):
    engine = create_engine(f'sqlite:///{tmp_path / "s.db"}')
    schema.run_script(engine, SQLITE_FILE)
    _compare_reflected(_reflect(engine), expected('sqlite'), 'SQLite from schema.sql')
    assert schema.missing(engine) == {}


def test_sqlite_from_the_file_equals_sqlite_from_the_code(tmp_path):
    """What SQLAlchemy would create on SQLite (the runtime tables do so) equals the file."""
    a = create_engine(f'sqlite:///{tmp_path / "a.db"}')
    b = create_engine(f'sqlite:///{tmp_path / "b.db"}')
    schema.run_script(a, SQLITE_FILE)
    for md in schema.metadatas():
        md.create_all(b)
    ra, rb = _reflect(a), _reflect(b)
    # create_all spells a unique column as a UNIQUE constraint just as the file does
    assert ra == rb


# ── (c) every runtime Table is in both files ─────────────────────

def test_every_table_defined_in_code_is_in_both_files():
    names = set(schema.tables())
    for t in ('sajha_state', 'sajha_state_events', 'obs_usage_events', 'connected_accounts', 'users'):
        assert t in names
    assert names == set(parse_schema(PG_FILE, 'postgresql')) == set(parse_schema(SQLITE_FILE, 'sqlite'))


def test_every_table_in_the_code_is_found_by_metadatas():
    """A new ``Table(`` or ``__tablename__`` anywhere in sajha/ must be registered in schema.metadatas()."""
    found = set()
    for f in (ROOT / 'sajha').rglob('*.py'):
        text = f.read_text(encoding='utf-8', errors='replace')
        found |= set(re.findall(r"__tablename__\s*=\s*['\"](\w+)['\"]", text))
        found |= set(re.findall(r"\bTable\(\s*['\"](\w+)['\"]", text))
    assert found and found <= set(schema.tables()), sorted(found - set(schema.tables()))


def test_seed_files_agree():
    def rows(path):
        return re.findall(r"\('([^']*)', '([^']*)'", path.read_text(encoding='utf-8'))
    assert rows(ROOT / 'db/scripts/postgresql/seed.sql') == rows(ROOT / 'db/scripts/sqlite/seed.sql')
    for d in ('postgresql', 'sqlite'):
        assert 'must_change_password' in (ROOT / f'db/scripts/{d}/seed.sql').read_text()


# ── start-up behaviour ───────────────────────────────────────────

def test_check_names_missing_tables_and_columns(tmp_path):
    from sqlalchemy import text
    engine = create_engine(f'sqlite:///{tmp_path / "x.db"}')
    with engine.begin() as c:
        c.execute(text('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)'))
    miss = schema.missing(engine)
    assert miss['roles'] is None and 'must_change_password' in miss['users']
    with pytest.raises(schema.SchemaNotReady):
        schema.check(engine, 'strict')
    assert schema.check(engine, 'warn') == miss
    with pytest.raises(ValueError):
        schema.check(engine, 'lenient')


def test_scripts_are_never_run_on_postgresql():
    class _Url:
        host, port, username, database = 'db', 5432, 'sajha', 'sajha'

    class _Pg:
        class dialect:
            name = 'postgresql'
        url = _Url()
    with pytest.raises(RuntimeError, match='does not run SQL scripts on postgresql'):
        schema.run_script(_Pg(), PG_FILE)
    assert schema.apply_command(_Pg()).endswith('-h db -U sajha -d sajha -f db/scripts/postgresql/schema.sql')


def test_cli_sql_and_check(tmp_path, capsys):
    from sajha.db.__main__ import main
    assert main(['sql', '--dialect', 'postgresql']) == 0
    assert capsys.readouterr().out == PG_FILE.read_text(encoding='utf-8')
    assert main(['sql', '--dialect', 'sqlite', '--seed']) == 0
    assert 'INSERT OR IGNORE INTO roles' in capsys.readouterr().out
    empty = tmp_path / 'empty.db'
    assert main(['check', '--url', f'sqlite:///{empty}']) == 3
    assert 'missing tables' in capsys.readouterr().out
    full = create_engine(f'sqlite:///{tmp_path / "full.db"}')
    schema.run_script(full, SQLITE_FILE)
    assert main(['check', '--url', f'sqlite:///{tmp_path / "full.db"}']) == 0
    for gone in ('migrate', 'status'):
        with pytest.raises(SystemExit):
            main([gone])


# ── (d) a real PostgreSQL ────────────────────────────────────────

PG_URL = os.environ.get('SAJHA_TEST_POSTGRES_URL', '')


@pytest.mark.skipif(not PG_URL, reason='set SAJHA_TEST_POSTGRES_URL to an empty PostgreSQL database')
def test_postgresql_file_applied_to_a_real_server_matches_the_code():
    engine = create_engine(PG_URL)
    with engine.begin() as c:                     # start from an empty public schema
        c.exec_driver_sql('DROP SCHEMA public CASCADE')
        c.exec_driver_sql('CREATE SCHEMA public')
    assert set(schema.missing(engine)) == set(schema.tables())
    with pytest.raises(schema.SchemaNotReady, match='psql -v ON_ERROR_STOP=1'):
        schema.check(engine, 'strict')
    assert inspect(engine).get_table_names() == []           # the check created nothing
    sql = PG_FILE.read_text(encoding='utf-8')
    with engine.begin() as c:
        c.exec_driver_sql(sql)
        c.exec_driver_sql(sql)                               # idempotent
        seed = (ROOT / 'db/scripts/postgresql/seed.sql').read_text(encoding='utf-8')
        c.exec_driver_sql(seed)
        c.exec_driver_sql(seed)
    _compare_reflected(_reflect(engine), expected('postgresql'), 'PostgreSQL from schema.sql')
    assert schema.check(engine, 'strict') == {}
    with engine.connect() as c:
        assert c.exec_driver_sql("SELECT must_change_password FROM users WHERE user_id = 'admin'").scalar() is True
        assert c.exec_driver_sql('SELECT COUNT(*) FROM roles').scalar() == 4
