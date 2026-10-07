"""
SAJHA MCP Server — the database schema: one SQL file per dialect, no migrations.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

``db/scripts/<sqlite|postgresql>/schema.sql`` holds every table, column, key and index
SAJHA uses; ``seed.sql`` beside it holds the default roles, permissions and admin user.

* SQLite (development): :func:`create_sqlite` runs ``schema.sql`` at start-up, and
  ``seed.sql`` when the database is new.  The state store, the usage ledger and the token
  vault also create their own tables on SQLite (for example in a separate
  ``state.database.url`` database).
* PostgreSQL (production): SAJHA runs no DDL.  An operator runs ``schema.sql`` (then
  ``seed.sql``) with psql, once.  At start-up :func:`check` compares the database with
  the tables and columns the code uses (every SQLAlchemy ``MetaData`` in SAJHA) and,
  when something is missing, refuses to start (``db.schema_check: strict``, the default)
  or warns (``warn``), naming what is missing and the psql command.

``tests/test_db_schema.py`` keeps both files in step with each other and with the code.
Owner guide: docs/getting-started/Database Setup.md
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DIALECTS = ('sqlite', 'postgresql')
SCHEMA_CHECK_MODES = ('strict', 'warn')
SCHEMA_FILE = 'schema.sql'
SEED_FILE = 'seed.sql'
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class SchemaNotReady(RuntimeError):
    """Tables or columns SAJHA uses are missing (db.schema_check: strict)."""


# ── files ────────────────────────────────────────────────────────

def scripts_root(configured: Optional[str] = None) -> Path:
    """``db.scripts_dir`` (default ``db/scripts``): relative to the working directory, else to the checkout."""
    p = Path(configured or 'db/scripts')
    if p.is_absolute():
        return p
    for base in (Path.cwd(), _REPO_ROOT):
        if (base / p).is_dir():
            return (base / p).resolve()
    return (Path.cwd() / p).resolve()


def _file(dialect: str, name: str, root: Optional[Path] = None) -> Path:
    if dialect not in DIALECTS:
        raise ValueError(f'unsupported dialect {dialect!r}; use one of {", ".join(DIALECTS)}')
    f = (root or scripts_root()) / dialect / name
    if not f.is_file():
        raise FileNotFoundError(f'schema file not found: {f} (db.scripts_dir)')
    return f


def schema_file(dialect: str, root: Optional[Path] = None) -> Path:
    return _file(dialect, SCHEMA_FILE, root)


def seed_file(dialect: str, root: Optional[Path] = None) -> Path:
    return _file(dialect, SEED_FILE, root)


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def psql_command(engine, path_text: str) -> str:
    """``psql -v ON_ERROR_STOP=1 ... -f <path_text>`` for ``engine``'s PostgreSQL database."""
    u = getattr(engine, 'url', None)
    if u is None:
        return f'psql -v ON_ERROR_STOP=1 -h HOST -U USER -d DBNAME -f {path_text}'
    port = f' -p {u.port}' if u.port and u.port != 5432 else ''
    return (f'psql -v ON_ERROR_STOP=1 -h {u.host or "localhost"}{port} -U {u.username or "USER"} '
            f'-d {u.database or "DBNAME"} -f {path_text}')


def apply_command(engine=None, file: str = SCHEMA_FILE, root: Optional[Path] = None) -> str:
    """The psql command that applies ``file`` to ``engine``'s PostgreSQL database."""
    return psql_command(engine, _display((root or scripts_root()) / 'postgresql' / file))


# ── SQL text ─────────────────────────────────────────────────────

def split_statements(sql: str) -> List[str]:
    """Split a script on ``;`` outside quotes and comments; drops comment-only chunks."""
    stmts, buf, i, n = [], [], 0, len(sql)
    in_str = False
    while i < n:
        c = sql[i]
        if in_str:
            buf.append(c)
            if c == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    buf.append("'")
                    i += 1
                else:
                    in_str = False
        elif c == "'":
            in_str = True
            buf.append(c)
        elif c == '-' and sql.startswith('--', i):
            j = sql.find('\n', i)
            i = n if j < 0 else j
            continue
        elif c == '/' and sql.startswith('/*', i):
            j = sql.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        elif c == ';':
            stmts.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(c)
        i += 1
    stmts.append(''.join(buf).strip())
    return [s for s in stmts if s and s.upper() not in ('BEGIN', 'COMMIT')]


def run_script(engine, path: Path) -> int:
    """Run a schema or seed file in one transaction.  SQLite only: SAJHA runs no DDL on PostgreSQL."""
    if engine.dialect.name != 'sqlite':
        raise RuntimeError(f'SAJHA does not run SQL scripts on {engine.dialect.name}; '
                           f'an operator applies them: {apply_command(engine, path.name)}')
    stmts = split_statements(path.read_text(encoding='utf-8'))
    with engine.begin() as conn:
        for stmt in stmts:
            conn.exec_driver_sql(stmt)
    return len(stmts)


# ── the schema file, parsed (CREATE TABLE / CREATE INDEX only) ─────

@dataclass
class TableDef:
    name: str
    statement: str                                   # the CREATE TABLE statement, without ';'
    columns: Dict[str, str] = field(default_factory=dict)   # column -> its definition text


@dataclass
class IndexDef:
    name: str
    table: str
    statement: str                                   # the CREATE [UNIQUE] INDEX statement, without ';'


@dataclass
class SchemaFile:
    dialect: str
    path: Path
    tables: Dict[str, TableDef] = field(default_factory=dict)     # in file order
    indexes: Dict[str, IndexDef] = field(default_factory=dict)    # in file order

    def indexes_of(self, table: str) -> List[IndexDef]:
        return [i for i in self.indexes.values() if i.table == table]


_CREATE_TABLE = re.compile(r'^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"?(\w+)"?\s*\(', re.I)
_CREATE_INDEX = re.compile(r'^CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"?(\w+)"?\s+ON\s+"?(\w+)"?',
                           re.I)
_TABLE_CONSTRAINT = re.compile(r'^(PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY|CONSTRAINT|CHECK)\b', re.I)


def _split_top_level(body: str) -> List[str]:
    parts, depth, buf, in_str = [], 0, [], False
    for ch in body:
        if ch == "'":
            in_str = not in_str
        elif not in_str and ch == '(':
            depth += 1
        elif not in_str and ch == ')':
            depth -= 1
        if ch == ',' and depth == 0 and not in_str:
            parts.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    parts.append(''.join(buf).strip())
    return [p for p in parts if p]


def _tidy(stmt: str) -> str:
    """The statement as written, minus the blank tails that removed comments leave."""
    return '\n'.join(line.rstrip() for line in stmt.splitlines() if line.strip())


def parse_schema_file(dialect: str, root: Optional[Path] = None) -> SchemaFile:
    """The tables (with each column's definition) and indexes of ``db/scripts/<dialect>/schema.sql``."""
    path = schema_file(dialect, root)
    out = SchemaFile(dialect, path)
    for stmt in split_statements(path.read_text(encoding='utf-8')):
        m = _CREATE_TABLE.match(stmt)
        if m:
            body = stmt[m.end():stmt.rindex(')')]
            t = TableDef(m.group(1), _tidy(stmt))
            for part in _split_top_level(body):
                part = ' '.join(part.split())
                if _TABLE_CONSTRAINT.match(part):
                    continue
                t.columns[part.split()[0].strip('"')] = part
            out.tables[t.name] = t
            continue
        m = _CREATE_INDEX.match(stmt)
        if m:
            out.indexes[m.group(1)] = IndexDef(m.group(1), m.group(2), _tidy(stmt))
    return out


def add_column_sql(dialect: str, table: str, definition: str) -> str:
    """``ALTER TABLE ... ADD COLUMN`` for one column definition of the schema file.

    PostgreSQL gets ``IF NOT EXISTS``. SQLite cannot add a column that is a primary key or
    unique, has a non-constant default, or is NOT NULL without a default; such a statement is
    printed with a comment saying so (the database file has to be recreated instead)."""
    if dialect == 'postgresql':
        return f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {definition};'
    up = definition.upper()
    why = []
    if 'PRIMARY KEY' in up or re.search(r'\bUNIQUE\b', up):
        why.append('a PRIMARY KEY or UNIQUE column')
    if re.search(r'DEFAULT\s+(CURRENT_TIMESTAMP|CURRENT_DATE|CURRENT_TIME|\()', up):
        why.append('a non-constant default')
    elif 'NOT NULL' in up and 'DEFAULT' not in up:
        why.append('NOT NULL without a default')
    stmt = f'ALTER TABLE {table} ADD COLUMN {definition};'
    if why:
        return (f'-- SQLite cannot add {" or ".join(why)} to an existing table; this statement will fail.\n'
                f'-- Recreate the development database instead (delete the file; SAJHA rebuilds it).\n{stmt}')
    return stmt


def _present_indexes(insp, table: str) -> set:
    names = set()
    try:
        names |= {i['name'] for i in insp.get_indexes(table) if i.get('name')}
    except Exception as e:                      # pragma: no cover - dialect quirks
        logger.debug(f'index reflection for {table}: {e}')
    try:
        names |= {u['name'] for u in insp.get_unique_constraints(table) if u.get('name')}
    except Exception as e:                      # pragma: no cover
        logger.debug(f'unique reflection for {table}: {e}')
    return names


def upgrade_statements(engine, root: Optional[Path] = None, dialect: Optional[str] = None,
                       miss: Optional[Dict[str, Optional[List[str]]]] = None) -> List[str]:
    """The DDL that brings ``engine``'s database up to the dialect's ``schema.sql``: a
    ``CREATE TABLE`` (and its indexes) for each missing table, ``ALTER TABLE ... ADD COLUMN``
    for each missing column, ``CREATE INDEX`` for each missing index. Statements are taken
    from the schema file, in its order. SAJHA only prints them; it never runs them.

    ``miss`` (from :func:`missing`) adds what the code uses but the file lacks, as comments."""
    from sqlalchemy import inspect
    dialect = dialect or ('postgresql' if engine.dialect.name == 'postgresql' else 'sqlite')
    sf = parse_schema_file(dialect, root)
    insp = inspect(engine)
    present = set(insp.get_table_names())
    out: List[str] = []
    for t in sf.tables.values():
        if t.name not in present:
            out.append(t.statement + ';')
            out.extend(i.statement + ';' for i in sf.indexes_of(t.name))
            continue
        have = {c['name'] for c in insp.get_columns(t.name)}
        out.extend(add_column_sql(dialect, t.name, d) for c, d in t.columns.items() if c not in have)
        have_ix = _present_indexes(insp, t.name)
        out.extend(i.statement + ';' for i in sf.indexes_of(t.name) if i.name not in have_ix)
    for table, cols in (miss or {}).items():
        if table not in sf.tables:
            out.append(f'-- {table}: used by the code but not in {sf.path.name}; report this as a bug')
        else:
            out.extend(f'-- {table}.{c}: used by the code but not in {sf.path.name}; report this as a bug'
                       for c in (cols or []) if c not in sf.tables[table].columns)
    return out


# ── what the code needs ─────────────────────────────────────────

def metadatas() -> list:
    """Every SQLAlchemy ``MetaData`` in SAJHA: the ORM models and the tables defined beside their code."""
    import sajha.db.models  # noqa: F401  (registers the ORM tables)
    from sajha.accounts.vault import metadata as accounts_md
    from sajha.ai.memory import metadata as memory_md
    from sajha.audit.chain import metadata as audit_md
    from sajha.core.state.database import _meta as state_md
    from sajha.db.base import Base
    from sajha.observability.usage import metadata as usage_md
    from sajha.quality.store import metadata as quality_md
    from sajha.workflows.store import metadata as workflows_md
    from sajha.net.integration.keystore import metadata as sajhanet_keys_md
    return [Base.metadata, state_md, usage_md, accounts_md, memory_md, audit_md, workflows_md, quality_md,
            sajhanet_keys_md]


def tables() -> dict:
    """``{name: Table}`` across :func:`metadatas`."""
    out = {}
    for md in metadatas():
        for name, t in md.tables.items():
            if name in out:
                raise RuntimeError(f'table {name} is defined twice in the code')
            out[name] = t
    return out


def missing(engine) -> Dict[str, Optional[List[str]]]:
    """``{table: None}`` for a missing table, ``{table: [columns]}`` for missing columns."""
    from sqlalchemy import inspect
    insp = inspect(engine)
    present = set(insp.get_table_names())
    out: Dict[str, Optional[List[str]]] = {}
    for name, t in sorted(tables().items()):
        if name not in present:
            out[name] = None
            continue
        have = {c['name'] for c in insp.get_columns(name)}
        cols = [c.name for c in t.columns if c.name not in have]
        if cols:
            out[name] = cols
    return out


def describe(miss: Dict[str, Optional[List[str]]]) -> List[str]:
    lines = []
    tabs = [t for t, cols in miss.items() if cols is None]
    if tabs:
        lines.append(f'missing tables ({len(tabs)}): {", ".join(tabs)}')
    for t, cols in miss.items():
        if cols is not None:
            lines.append(f'missing columns in {t}: {", ".join(cols)}')
    return lines


def _indent(stmts: List[str], pad: str = '    ') -> str:
    return ''.join(pad + line + '\n' for st in stmts for line in st.splitlines())


def _statements(engine, miss, root: Optional[Path]) -> List[str]:
    try:
        return upgrade_statements(engine, root, miss=miss)
    except Exception as e:                  # the message must never fail; the names above still stand
        logger.debug(f'upgrade statements unavailable: {e}')
        return []


def not_ready_message(engine, miss, root: Optional[Path] = None) -> str:
    where = engine.url.render_as_string(hide_password=True)
    head = f'database schema is not ready ({where}):\n' + ''.join(f'  {l}\n' for l in describe(miss))
    stmts = _statements(engine, miss, root)
    helper = ('  The same statements, for review or a file:  python -m sajha.db upgrade-sql\n'
              '  Guide: docs/getting-started/Database Setup.md')
    if engine.dialect.name == 'sqlite':
        body = ('  SAJHA created what it could from db/scripts/sqlite/schema.sql, but it never alters an\n'
                '  existing table. This development database predates the schema: recreate it (delete the\n'
                '  file; SAJHA rebuilds and seeds it at the next start). To keep its data instead, run these\n'
                '  statements yourself (SAJHA prints them; it does not run them):\n')
        return head + body + (_indent(stmts) if stmts else '    (no statements could be derived)\n') + helper
    new_db = all(cols is None for cols in miss.values())
    lines = [head, f'  SAJHA does not create or alter tables on {engine.dialect.name}. ']
    if new_db:
        lines.append('Create the schema, then the default roles and admin user:\n'
                     f'    {apply_command(engine, SCHEMA_FILE, root)}\n'
                     f'    {apply_command(engine, SEED_FILE, root)}\n')
    else:
        lines.append(f'Review and run these statements (from {SCHEMA_FILE}) as the schema owner:\n')
        lines.append(_indent(stmts) if stmts else
                     f'    {apply_command(engine, SCHEMA_FILE, root)}   (creates missing tables only)\n')
        lines.append(helper.split('\n')[0] + ' > upgrade.sql\n'
                     f'    {psql_command(engine, "upgrade.sql")}\n')
    lines.append('  Check with:  python -m sajha.db check.  Guide: docs/getting-started/Database Setup.md\n'
                 '  (db.schema_check: warn starts anyway, with features failing where tables are missing.)')
    return ''.join(lines)


# ── start-up ─────────────────────────────────────────────────────

def create_sqlite(engine, root: Optional[Path] = None) -> bool:
    """Development: run schema.sql, and seed.sql on a new database.  Returns True when the database was new.

    On an existing database whose tables predate the file (an index on a column the table
    lacks fails the whole script), the statements are retried one by one so missing tables
    are still created; what fails is left to :func:`check`, which prints the SQL."""
    from sqlalchemy import inspect
    new = not inspect(engine).has_table('users')
    path = schema_file('sqlite', root)
    try:
        n = run_script(engine, path)
    except Exception as e:
        if new:
            raise
        failed = _run_each(engine, path)
        logger.warning(f'  Schema: {len(failed)} statement(s) of {path.name} do not fit this older SQLite '
                       f'database ({e.__class__.__name__}); the schema check below prints what to run')
        return False
    if new:
        run_script(engine, seed_file('sqlite', root))
        logger.info(f'  Schema: created a new SQLite database ({n} statements) and seeded the default '
                    'roles and admin user')
    else:
        logger.info('  Schema: SQLite schema.sql applied (existing tables are never altered)')
    return new


def _run_each(engine, path: Path) -> List[str]:
    """SQLite only: run each statement in its own transaction; return the ones that failed."""
    failed = []
    for stmt in split_statements(path.read_text(encoding='utf-8')):
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(stmt)
        except Exception as e:
            logger.debug(f'schema statement skipped: {e}')
            failed.append(stmt)
    return failed


# System Notices (docs/architecture/System Notices.md): the start-up schema check is the
# source of ``db.schema``; it raises the notice itself and clears it when the schema is complete.
NOTICE_ID = 'db.schema'


def _notice(statements: Optional[List[str]], severity: str = 'error', summary: str = '') -> None:
    """Raise (statements given) or clear (None) the ``db.schema`` notice. Never raises."""
    try:
        from sajha import notices
        if statements is None:
            notices.clear_notice(NOTICE_ID)
            return
        sql = ('\n\nSQL to run (review first; SAJHA never runs it; python -m sajha.db upgrade-sql prints it):\n'
               + '\n'.join(statements)) if statements else ''
        notices.raise_notice(NOTICE_ID, severity=severity, source='db', title='Database schema is out of date',
                             detail=summary + sql, link='/help/guides/Database%20Setup.md', ttl_minutes=0)
    except Exception as e:
        logger.debug(f'schema notice: {e}')


def check(engine, mode: str = 'strict', root: Optional[Path] = None,
          notify: bool = False) -> Dict[str, Optional[List[str]]]:
    """Raise (strict) or warn (warn) when tables or columns the code uses are missing.

    Missing indexes never stop start-up; they are logged with the ``CREATE INDEX`` to run.
    ``notify`` (start-up): also raise or clear the ``db.schema`` system notice."""
    mode = (mode or 'strict').strip().lower()
    if mode not in SCHEMA_CHECK_MODES:
        raise ValueError(f'db.schema_check must be strict or warn, not {mode!r}')
    miss = missing(engine)
    if not miss:
        logger.info(f'  Schema check: {engine.dialect.name} has every table and column SAJHA uses')
        extra = _statements(engine, None, root)
        if extra:
            logger.warning('  Schema check: indexes of the schema file are missing (start-up continues). '
                           'Review and run:\n' + _indent(extra) + '  (python -m sajha.db upgrade-sql prints them)')
        if notify:
            _notice(extra or None, 'warning', 'Indexes of the schema file are missing; queries may be slow.')
        if engine.dialect.name != 'sqlite':
            _warn_if_unseeded(engine, root)
        return miss
    msg = not_ready_message(engine, miss, root)
    if mode == 'strict':
        raise SchemaNotReady(msg)
    logger.warning('  ' + msg)
    if notify:
        _notice(_statements(engine, miss, root), 'error',
                'Tables or columns SAJHA uses are missing (db.schema_check: warn started anyway; features '
                'that use them fail):\n' + '\n'.join(describe(miss)))
    return miss


def _warn_if_unseeded(engine, root: Optional[Path]) -> None:
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            n = conn.execute(text('SELECT COUNT(*) FROM roles')).scalar()
    except Exception as e:
        logger.debug(f'seed check skipped: {e}')
        return
    if not n:
        logger.warning('  No roles in the database: nobody can sign in until the default roles and admin '
                       f'user exist. Run once:  {apply_command(engine, SEED_FILE, root)}')
