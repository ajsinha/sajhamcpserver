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


def apply_command(engine=None, file: str = SCHEMA_FILE, root: Optional[Path] = None) -> str:
    """The psql command that applies ``file`` to ``engine``'s PostgreSQL database."""
    path = _display((root or scripts_root()) / 'postgresql' / file)
    u = getattr(engine, 'url', None)
    if u is None:
        return f'psql -v ON_ERROR_STOP=1 -h HOST -U USER -d DBNAME -f {path}'
    port = f' -p {u.port}' if u.port and u.port != 5432 else ''
    return (f'psql -v ON_ERROR_STOP=1 -h {u.host or "localhost"}{port} -U {u.username or "USER"} '
            f'-d {u.database or "DBNAME"} -f {path}')


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
    return [Base.metadata, state_md, usage_md, accounts_md, memory_md, audit_md, workflows_md, quality_md]


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


def not_ready_message(engine, miss, root: Optional[Path] = None) -> str:
    where = engine.url.render_as_string(hide_password=True)
    head = f'database schema is not ready ({where}):\n' + ''.join(f'  {l}\n' for l in describe(miss))
    if engine.dialect.name == 'sqlite':
        return head + (
            '  SAJHA created what it could from db/scripts/sqlite/schema.sql, but it never alters an\n'
            '  existing table. This development database predates those columns: delete the file to\n'
            '  have it recreated, or add them by hand. Guide: docs/getting-started/Database Setup.md')
    new_db = all(cols is None for cols in miss.values())
    lines = [head, f'  SAJHA does not create or alter tables on {engine.dialect.name}. ']
    if new_db:
        lines.append('Create the schema, then the default roles and admin user:\n'
                     f'    {apply_command(engine, SCHEMA_FILE, root)}\n'
                     f'    {apply_command(engine, SEED_FILE, root)}\n')
    else:
        lines.append(f'Run {SCHEMA_FILE} for missing tables:\n'
                     f'    {apply_command(engine, SCHEMA_FILE, root)}\n'
                     '  Missing columns of an existing table: run the SQL that the release notes\n'
                     '  (CHANGELOG.md) list for this upgrade.\n')
    lines.append('  Check with:  python -m sajha.db check.  Guide: docs/getting-started/Database Setup.md\n'
                 '  (db.schema_check: warn starts anyway, with features failing where tables are missing.)')
    return ''.join(lines)


# ── start-up ─────────────────────────────────────────────────────

def create_sqlite(engine, root: Optional[Path] = None) -> bool:
    """Development: run schema.sql, and seed.sql on a new database.  Returns True when the database was new."""
    from sqlalchemy import inspect
    new = not inspect(engine).has_table('users')
    n = run_script(engine, schema_file('sqlite', root))
    if new:
        run_script(engine, seed_file('sqlite', root))
        logger.info(f'  Schema: created a new SQLite database ({n} statements) and seeded the default '
                    'roles and admin user')
    else:
        logger.info('  Schema: SQLite schema.sql applied (existing tables are never altered)')
    return new


def check(engine, mode: str = 'strict', root: Optional[Path] = None) -> Dict[str, Optional[List[str]]]:
    """Raise (strict) or warn (warn) when tables or columns the code uses are missing."""
    mode = (mode or 'strict').strip().lower()
    if mode not in SCHEMA_CHECK_MODES:
        raise ValueError(f'db.schema_check must be strict or warn, not {mode!r}')
    miss = missing(engine)
    if not miss:
        logger.info(f'  Schema check: {engine.dialect.name} has every table and column SAJHA uses')
        if engine.dialect.name != 'sqlite':
            _warn_if_unseeded(engine, root)
        return miss
    msg = not_ready_message(engine, miss, root)
    if mode == 'strict':
        raise SchemaNotReady(msg)
    logger.warning('  ' + msg)
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
