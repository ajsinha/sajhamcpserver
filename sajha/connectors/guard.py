"""
SAJHA MCP Server — Data Connectors: the statement guard for caller-written SQL.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

:func:`check` accepts exactly one read-only query and returns the text to run, or raises
:class:`GuardError` saying why not. It requires one statement; a SELECT / WITH ... SELECT /
set operation / VALUES; no DML or DDL anywhere (a data-modifying CTE, ``SELECT ... INTO``,
locking clauses); no denied function; only tables the connection's catalog allows; and the
masking rules respected. With sqlglot installed the checks run on its syntax tree in the
connection's dialect; without it, a conservative scanner over the token stream
(sajha/connectors/sqltext.py) refuses anything it cannot verify. Denied functions are always
also checked on the token stream. Design: docs/architecture/Data Connectors.md, sections 5 and 7.
"""

from __future__ import annotations

import fnmatch
import importlib.util
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Set, Tuple

from sajha.connectors import sqltext
from sajha.connectors.model import Connection, MaskRule

#: connection kind -> sqlglot dialect (also the tokenizer's dialect)
DIALECTS = {
    'postgresql': 'postgres', 'pgvector': 'postgres', 'redshift': 'redshift', 'mysql': 'mysql',
    'mariadb': 'mysql', 'sqlserver': 'tsql', 'oracle': 'oracle', 'snowflake': 'snowflake',
    'bigquery': 'bigquery', 'databricks': 'databricks', 'sqlite': 'sqlite', 'duckdb': 'duckdb',
}
#: dialects where ``LIMIT n`` is appended to a query that has none
LIMIT_DIALECTS = ('postgres', 'redshift', 'mysql', 'sqlite', 'duckdb', 'snowflake', 'bigquery', 'databricks')

#: functions that touch files, the network, other servers, dynamic SQL, server state or sequences
DENIED_FUNCTIONS = {
    'pg_read_file', 'pg_read_binary_file', 'pg_ls_dir', 'pg_stat_file', 'pg_ls_logdir', 'pg_ls_waldir',
    'pg_ls_tmpdir', 'pg_ls_archive_statusdir', 'pg_terminate_backend', 'pg_cancel_backend', 'pg_reload_conf',
    'pg_rotate_logfile', 'pg_promote', 'pg_switch_wal', 'pg_create_restore_point', 'pg_notify',
    'pg_logical_emit_message', 'pg_import_system_collations', 'set_config', 'nextval', 'setval',
    'query_to_xml', 'query_to_xml_and_xmlschema', 'query_to_xmlschema', 'cursor_to_xml',
    'cursor_to_xmlschema', 'table_to_xml', 'table_to_xml_and_xmlschema', 'schema_to_xml',
    'database_to_xml', 'database_to_xml_and_xmlschema', 'pg_file_write', 'pg_file_rename', 'pg_file_unlink',
    'load_file', 'benchmark', 'get_lock', 'release_lock', 'release_all_locks', 'master_pos_wait',
    'source_pos_wait', 'sys_exec', 'sys_eval',
    'openrowset', 'opendatasource', 'openquery', 'openxml',
    'glob', 'load_extension', 'readfile', 'writefile', 'edit', 'fts5_vocab',
    'external_query', 'http_request', 'read_kafka',
    'getvariable', 'current_setting',
}
#: denied by prefix (lower case)
DENIED_PREFIXES = ('pg_read_', 'pg_ls_', 'pg_file_', 'pg_advisory', 'pg_try_advisory', 'lo_', 'dblink',
                   'xp_', 'sp_', 'utl_', 'dbms_', 'read_', 'system$', 'sys.', 'sqlite_', 'duckdb_secret',
                   'pg_replication', 'pg_create_', 'pg_drop_', 'pg_start_', 'pg_stop_', 'pg_backup')
#: table functions allowed in FROM
TABLE_FUNCTIONS = {'generate_series', 'exploding_generate_series', 'unnest', 'explode', 'range', 'generator'}
#: statement keywords that may never appear in a caller's query (scanner)
DENY_KEYWORDS = {'INSERT', 'UPDATE', 'DELETE', 'MERGE', 'UPSERT', 'INTO', 'LOCK', 'CREATE', 'DROP', 'ALTER',
                 'TRUNCATE', 'GRANT', 'REVOKE', 'COPY', 'CALL', 'EXEC', 'EXECUTE', 'SET', 'ATTACH', 'DETACH',
                 'PRAGMA', 'VACUUM', 'COMMIT', 'ROLLBACK', 'SAVEPOINT'}
_FIRST_WORDS = ('SELECT', 'WITH', 'VALUES')
_CLAUSE_WORDS = {'WHERE', 'GROUP', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET', 'FETCH', 'UNION', 'INTERSECT', 'EXCEPT',
                 'MINUS', 'JOIN', 'INNER', 'LEFT', 'RIGHT', 'FULL', 'CROSS', 'NATURAL', 'ON', 'USING', 'WINDOW',
                 'QUALIFY', 'FOR', 'OUTER', 'LATERAL', 'SAMPLE', 'TABLESAMPLE', 'PIVOT', 'UNPIVOT', 'CONNECT',
                 'START', 'WITH', 'RETURNING', 'AS', 'TOP', 'SELECT', 'FROM', 'APPLY'}

#: (catalog, schema, table) -> (schema, table) of an allowed table, or None
Resolver = Callable[[str, str, str], Optional[Tuple[str, str]]]


class GuardError(ValueError):
    """A caller's SQL was refused before it reached the database."""


@dataclass
class Checked:
    sql: str                                       # the text to run (``:name`` placeholders kept)
    tables: List[Tuple[str, str]] = field(default_factory=list)
    parser: str = 'sqlglot'
    limited: bool = False


def sqlglot_available() -> bool:
    try:
        return importlib.util.find_spec('sqlglot') is not None
    except (ImportError, ValueError):
        return False


_force_scanner = False


def use_scanner(on: bool = True) -> None:
    """Tests: force the fallback scanner even when sqlglot is installed."""
    global _force_scanner
    _force_scanner = on


def _denied_function(name: str) -> bool:
    n = name.lower().strip('"`[]')
    if n in DENIED_FUNCTIONS:
        return True
    return any(n.startswith(p) for p in DENIED_PREFIXES)


# ── token-level checks (both paths) ─────────────────────────────────────

def _check_functions_tokens(code: List[sqltext.Token]) -> None:
    for i, t in enumerate(code):
        if t.kind not in ('word', 'qident'):
            continue
        nxt = code[i + 1] if i + 1 < len(code) else None
        if nxt is not None and nxt.kind == 'op' and nxt.text == '(':
            # the whole dotted name: a.b.c(
            parts = [t.ident]
            j = i - 1
            while j >= 1 and code[j].kind == 'op' and code[j].text == '.' and code[j - 1].kind in ('word', 'qident'):
                parts.insert(0, code[j - 1].ident)
                j -= 2
            for k in range(len(parts)):
                dotted = '.'.join(parts[k:])
                if _denied_function(dotted) or _denied_function(parts[k]):
                    raise GuardError(f'function {".".join(parts)}() is not allowed on a data connection '
                                     f'(it can reach files, the network, other servers or server state)')
            if len(parts) > 1 and _denied_function(parts[0] + '.'):
                raise GuardError(f'function {".".join(parts)}() is not allowed on a data connection')


def _relevant_rules(conn: Connection, tables: List[Tuple[str, str]]) -> List[MaskRule]:
    out = []
    for r in conn.masking:
        tg = r.table_glob
        if tg is None:
            out.append(r)
            continue
        for s, t in tables:
            full = f'{s}.{t}'.lower() if s else t.lower()
            if fnmatch.fnmatchcase(t.lower(), tg) or fnmatch.fnmatchcase(full, tg):
                out.append(r)
                break
    return out


def _masked(name: str, rules: List[MaskRule]) -> Optional[MaskRule]:
    for r in rules:
        if fnmatch.fnmatchcase(name.lower(), r.column_glob):
            return r
    return None


# ── sqlglot path ────────────────────────────────────────────────────────

def _exp_classes(*names):
    from sqlglot import exp
    return tuple(c for c in (getattr(exp, n, None) for n in names) if isinstance(c, type))


def _check_sqlglot(text: str, conn: Connection, resolve: Resolver, dialect: str) -> Checked:
    import sqlglot
    from sqlglot import exp
    try:
        trees = [t for t in sqlglot.parse(text, read=dialect) if t is not None]
    except Exception as e:                                    # ParseError, TokenError
        msg = str(e).split('\n', 1)[0][:300]
        raise GuardError(f'the SQL could not be parsed as {dialect}: {msg}') from None
    if len(trees) != 1:
        raise GuardError(f'exactly one statement is allowed; got {len(trees)}')
    root = trees[0]
    roots = _exp_classes('Select', 'Union', 'Intersect', 'Except', 'SetOperation', 'Subquery', 'Values')
    if not isinstance(root, roots):
        raise GuardError(f'only a read-only query (SELECT) is allowed; got {root.key.upper()}')
    forbidden = _exp_classes('Insert', 'Update', 'Delete', 'Merge', 'Create', 'Drop', 'Alter', 'AlterTable',
                             'Command', 'Copy', 'Set', 'Pragma', 'Transaction', 'Commit', 'Rollback', 'Use',
                             'LoadData', 'Grant', 'Revoke', 'TruncateTable', 'Attach', 'Detach', 'Kill', 'Analyze',
                             'Describe', 'Cache', 'Uncache', 'Refresh', 'Into', 'Lock', 'Show', 'Execute')
    for node in root.walk():
        node = node[0] if isinstance(node, tuple) else node
        if isinstance(node, forbidden):
            what = {'into': 'SELECT ... INTO', 'lock': 'a locking clause (FOR UPDATE / FOR SHARE)'}.get(
                node.key, node.key.upper())
            raise GuardError(f'{what} is not allowed: only read-only queries')
    # functions
    for f in root.find_all(exp.Func):
        name = f.name if isinstance(f, exp.Anonymous) else f.sql_name()
        if name and _denied_function(name):
            raise GuardError(f'function {name.lower()}() is not allowed on a data connection')
    for d in root.find_all(exp.Dot):
        left = d.this
        if isinstance(left, (exp.Column, exp.Identifier, exp.Var)) and _denied_function(left.name + '.'):
            raise GuardError(f'package {left.name}.* is not allowed on a data connection')
    # tables
    ctes = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    tables: List[Tuple[str, str]] = []
    aliases: Set[str] = set()
    for t in root.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            fn = t.this
            name = (fn.name if isinstance(fn, exp.Anonymous) else getattr(fn, 'sql_name', lambda: '')()).lower() \
                if isinstance(fn, exp.Func) else ''
            if name not in TABLE_FUNCTIONS:
                raise GuardError(f'table function {name or t.sql(dialect=dialect)[:60]} is not allowed in FROM '
                                 f'(allowed: {", ".join(sorted(TABLE_FUNCTIONS))})')
            continue
        if not t.db and not t.catalog and t.name.lower() in ctes:
            continue
        hit = resolve(t.catalog, t.db, t.name)
        if hit is None:
            shown = '.'.join(p for p in (t.catalog, t.db, t.name) if p)
            raise GuardError(f'table {shown} is not available on connection {conn.id} '
                             f'(see {conn.id}__list_tables)')
        tables.append(hit)
        aliases.add(t.name.lower())
        if t.alias:
            aliases.add(t.alias.lower())
    # masking
    rules = _relevant_rules(conn, tables)
    if rules:
        top_select = root if isinstance(root, exp.Select) else None
        for c in root.find_all(exp.Column):
            if isinstance(c.this, exp.Star):
                if c.parent is not top_select:
                    raise GuardError('a table with masked columns may not be passed whole (t.*) into a function '
                                     'or subquery; select its columns at the top level')
                continue
            r = _masked(c.name, rules)
            if r is None:
                if not c.table and c.name.lower() in aliases and not isinstance(c.parent, exp.Dot) \
                        and c.parent is not top_select:
                    raise GuardError(f'{c.name} is a table with masked columns; it may not be used as a value')
                continue
            if r.mode == 'hide':
                raise GuardError(f'column {c.name} is hidden on this connection')
            parent = c.parent
            plain = (parent is top_select and c in top_select.expressions) or (
                isinstance(parent, exp.Alias) and parent.alias.lower() == c.name.lower()
                and parent.parent is top_select)
            if not plain:
                raise GuardError(f'column {c.name} is masked: select it as a plain column of the outermost '
                                 f'SELECT (not in WHERE, JOIN, ORDER BY, a function, a subquery or under '
                                 f'another name)')
        for s in root.find_all(exp.Star):
            p = s.parent
            if isinstance(p, exp.Count) or (isinstance(p, exp.Column) and p.parent is top_select):
                continue
            if p is not top_select:
                raise GuardError('SELECT * over a table with masked columns is allowed only at the top level '
                                 '(not in a subquery, CTE or set operation)')
    return Checked(text, tables, 'sqlglot')


# ── scanner path ────────────────────────────────────────────────────────

def _read_name(code: List[sqltext.Token], i: int) -> Tuple[List[str], int]:
    """A dotted name starting at code[i]: (parts, index after it)."""
    parts = []
    while i < len(code) and code[i].kind in ('word', 'qident'):
        parts.append(code[i].ident)
        if i + 2 < len(code) and code[i + 1].kind == 'op' and code[i + 1].text == '.':
            i += 2
            continue
        i += 1
        break
    return parts, i


def _check_scanner(text: str, conn: Connection, resolve: Resolver, dialect: str) -> Checked:
    toks = sqltext.tokenize(text, dialect)
    code = sqltext.code(toks)
    if not code:
        raise GuardError('SQL query is required')
    if sqltext.count_statements(toks) != 1:
        raise GuardError('exactly one statement is allowed')
    first = code[0]
    if not ((first.kind == 'word' and first.upper in _FIRST_WORDS) or (first.kind == 'op' and first.text == '(')):
        raise GuardError(f'only a read-only query (SELECT) is allowed; got {first.text.upper()[:30]}')
    for i, t in enumerate(code):
        if t.kind == 'word':
            u = t.upper
            if u in DENY_KEYWORDS:
                raise GuardError(f'{u} is not allowed: only read-only queries')
            if u == 'FOR' and i + 1 < len(code) and code[i + 1].upper in ('UPDATE', 'SHARE', 'NO', 'KEY'):
                raise GuardError('a locking clause (FOR UPDATE / FOR SHARE) is not allowed')
        if t.kind == 'op' and t.text == ';':
            raise GuardError('exactly one statement is allowed')
    # CTE names: <name> [ ( cols ) ] AS (
    ctes: Set[str] = set()
    for i, t in enumerate(code):
        if t.kind in ('word', 'qident') and i + 1 < len(code):
            j = i + 1
            if code[j].kind == 'op' and code[j].text == '(':
                depth = 0
                while j < len(code):
                    if code[j].text == '(':
                        depth += 1
                    elif code[j].text == ')':
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                j += 1
            if j + 1 < len(code) and code[j].upper == 'AS' and code[j + 1].text == '(' and \
                    (i == 0 or code[i - 1].upper in ('WITH', 'RECURSIVE', ',')):
                ctes.add(t.ident.lower())
    # tables after FROM / JOIN (and comma joins)
    tables: List[Tuple[str, str]] = []
    consumed: Set[int] = set()
    aliases: Set[str] = set()
    i = 0
    while i < len(code):
        t = code[i]
        if t.kind == 'word' and t.upper in ('FROM', 'JOIN'):
            j = i + 1
            while True:
                while j < len(code) and code[j].kind == 'word' and code[j].upper in ('ONLY', 'LATERAL'):
                    j += 1
                if j >= len(code):
                    break
                if code[j].kind == 'op' and code[j].text == '(':
                    break                                          # a subquery: scanned as it is
                if code[j].kind not in ('word', 'qident'):
                    raise GuardError(f'cannot verify the table after {t.upper}: rewrite the query '
                                     f'(or install sqlglot)')
                start = j
                parts, j = _read_name(code, j)
                if j < len(code) and code[j].kind == 'op' and code[j].text == '(':
                    name = '.'.join(parts).lower()
                    if name not in TABLE_FUNCTIONS:
                        raise GuardError(f'table function {name} is not allowed in FROM '
                                         f'(allowed: {", ".join(sorted(TABLE_FUNCTIONS))})')
                    break
                consumed.update(range(start, j))
                if len(parts) == 1 and parts[0].lower() in ctes:
                    pass
                else:
                    if len(parts) > 3:
                        raise GuardError(f'table {".".join(parts)}: too many name parts')
                    cat, sch, tab = ([''] * (3 - len(parts)) + parts)
                    hit = resolve(cat, sch, tab)
                    if hit is None:
                        raise GuardError(f'table {".".join(parts)} is not available on connection {conn.id} '
                                         f'(see {conn.id}__list_tables)')
                    tables.append(hit)
                    aliases.add(tab.lower())
                # alias
                if j < len(code) and code[j].upper == 'AS':
                    j += 1
                if j < len(code) and code[j].kind in ('word', 'qident') and code[j].upper not in _CLAUSE_WORDS:
                    aliases.add(code[j].ident.lower())
                    consumed.add(j)
                    j += 1
                if t.upper == 'FROM' and j < len(code) and code[j].kind == 'op' and code[j].text == ',':
                    j += 1
                    continue
                break
            i = max(i + 1, j)
            continue
        i += 1
    rules = _relevant_rules(conn, tables)
    if rules:
        depth = 0
        for i, t in enumerate(code):
            if t.text == '(':
                depth += 1
            elif t.text == ')':
                depth -= 1
            if t.kind == 'word' and t.upper in ('UNION', 'INTERSECT', 'EXCEPT', 'MINUS'):
                raise GuardError('set operations over a table with masked columns are not allowed '
                                 '(install sqlglot for finer checks)')
            if t.text == '*' and depth > 0:
                prev = code[i - 2].upper if i >= 2 else ''
                if not (prev == 'COUNT' and code[i - 1].text == '('):
                    raise GuardError('* over a table with masked columns is allowed only at the top level')
            if i in consumed or t.kind not in ('word', 'qident'):
                continue
            r = _masked(t.ident, rules)
            if r is not None:
                raise GuardError(f'column {t.ident} is masked on this connection; without sqlglot it may not be '
                                 f'named in a query (SELECT * returns it masked)')
            nxt = code[i + 1] if i + 1 < len(code) else None
            if t.ident.lower() in aliases and not (nxt is not None and nxt.text == '.'):
                raise GuardError(f'{t.ident} is a table with masked columns; it may not be used as a value')
    return Checked(text, tables, 'scanner')


# ── entry point ─────────────────────────────────────────────────────────

def _has_top_level_limit(text: str, dialect: str) -> bool:
    depth = 0
    for t in sqltext.code(sqltext.tokenize(text, dialect)):
        if t.text == '(':
            depth += 1
        elif t.text == ')':
            depth -= 1
        elif depth == 0 and t.kind == 'word' and t.upper in ('LIMIT', 'FETCH', 'TOP'):
            return True
    return False


def _analysis_text(text: str, dialect: str) -> str:
    """The text with ``:name`` parameters replaced by NULL, for the parser."""
    return ''.join('NULL' if t.kind == 'param' else t.text for t in sqltext.tokenize(text, dialect))


def check(sql, conn: Connection, resolve: Resolver, limit: Optional[int] = None,
          require_parser: bool = False) -> Checked:
    if not isinstance(sql, str) or not sql.strip():
        raise GuardError('SQL query is required')
    if len(sql) > 100_000:
        raise GuardError('the SQL is too long (at most 100000 characters)')
    dialect = DIALECTS.get(conn.kind, '')
    try:
        text = sqltext.strip_trailing_semicolons(sql, dialect)
        code = sqltext.code(sqltext.tokenize(text, dialect))
    except sqltext.SQLTextError as e:
        raise GuardError(str(e)) from None
    if not code:
        raise GuardError('SQL query is required')
    _check_functions_tokens(code)
    use_parser = sqlglot_available() and not _force_scanner
    if require_parser and not use_parser:
        raise GuardError('caller-written SQL needs sqlglot on this server (connectors.require_sqlglot): '
                         "pip install 'sqlglot'")

    def run(t: str) -> Checked:
        if use_parser:
            return _check_sqlglot(_analysis_text(t, dialect), conn, resolve, dialect)
        return _check_scanner(t, conn, resolve, dialect)

    checked = run(text)
    checked.sql = text
    if limit is not None and dialect in LIMIT_DIALECTS and not _has_top_level_limit(text, dialect):
        limited = f'{text}\nLIMIT {int(limit)}'
        again = run(limited)
        again.sql, again.limited = limited, True
        return again
    return checked


def quote(name: str, style: str = '"') -> str:
    """A quoted identifier (only for names read back from, or checked against, the catalog)."""
    if not isinstance(name, str) or not name or '\x00' in name:
        raise GuardError(f'invalid identifier {name!r}')
    if style == '[':
        return '[' + name.replace(']', ']]') + ']'
    return style + name.replace(style, style * 2) + style

