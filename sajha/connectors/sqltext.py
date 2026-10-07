"""
SAJHA MCP Server — Data Connectors: a small SQL tokenizer.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com

Enough lexing to tell code from comments, string literals and quoted identifiers in every
supported dialect, so that

* the fallback statement guard (sajha/connectors/guard.py, when sqlglot is not installed)
  sees keywords, function names and table names only where they are code;
* ``:name`` parameters are rewritten to the driver's placeholder style without touching a
  ``::`` cast, a string or a comment.

It fails closed: an unterminated string, quoted identifier or block comment is an error.
Backslash escapes inside single-quoted strings are honoured only for the dialects that use
them by default (MySQL/MariaDB, BigQuery, Databricks, Snowflake); elsewhere a backslash is an
ordinary character, so a string never "swallows" code the database would run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

BACKSLASH_DIALECTS = ('mysql', 'bigquery', 'databricks', 'snowflake')
BACKTICK_DIALECTS = ('mysql', 'bigquery', 'databricks', 'sqlite')
BRACKET_DIALECTS = ('tsql', 'sqlite')
DOLLAR_DIALECTS = ('postgres', 'redshift', 'duckdb', 'snowflake')

_WORD = re.compile(r'[A-Za-z_\u0080-￿][A-Za-z0-9_$#\u0080-￿]*')
_NUMBER = re.compile(r'(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?')
_DOLLAR_TAG = re.compile(r'\$([A-Za-z_][A-Za-z0-9_]*)?\$')
_PARAM = re.compile(r':([A-Za-z_][A-Za-z0-9_]{0,63})')


class SQLTextError(ValueError):
    """The text cannot be tokenized safely (an unterminated string, identifier or comment)."""


@dataclass
class Token:
    kind: str      # ws | comment | string | qident | word | number | param | op
    text: str
    pos: int

    @property
    def upper(self) -> str:
        return self.text.upper()

    @property
    def ident(self) -> str:
        """An identifier's name: a word as written, a quoted identifier unquoted."""
        if self.kind == 'qident':
            q = self.text[0]
            inner = self.text[1:-1]
            return inner.replace(q * 2, q) if q != '[' else inner.replace(']]', ']')
        return self.text


def tokenize(sql: str, dialect: str = '') -> List[Token]:
    if not isinstance(sql, str):
        raise SQLTextError('SQL must be text')
    out: List[Token] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            j = i + 1
            while j < n and sql[j].isspace():
                j += 1
            out.append(Token('ws', sql[i:j], i))
            i = j
            continue
        if c == '-' and sql.startswith('--', i):
            j = sql.find('\n', i)
            j = n if j < 0 else j
            out.append(Token('comment', sql[i:j], i))
            i = j
            continue
        if c == '#' and dialect == 'mysql':
            j = sql.find('\n', i)
            j = n if j < 0 else j
            out.append(Token('comment', sql[i:j], i))
            i = j
            continue
        if c == '/' and sql.startswith('/*', i):
            # nested block comments (PostgreSQL) are counted; others end at the first */
            depth, j = 1, i + 2
            while j < n and depth:
                if sql.startswith('*/', j):
                    depth -= 1
                    j += 2
                elif dialect in ('postgres', 'redshift') and sql.startswith('/*', j):
                    depth += 1
                    j += 2
                else:
                    j += 1
            if depth:
                raise SQLTextError('unterminated /* comment')
            out.append(Token('comment', sql[i:j], i))
            i = j
            continue
        if c == "'" or (c in 'eEnNbBxXrR' and i + 1 < n and sql[i + 1] == "'"):
            start = i
            prefix = '' if c == "'" else c.upper()
            j = i + (1 if c == "'" else 2)
            backslash = dialect in BACKSLASH_DIALECTS or (prefix == 'E' and dialect in ('postgres', 'redshift'))
            if prefix == 'R':
                backslash = False
            while True:
                if j >= n:
                    raise SQLTextError('unterminated string literal')
                ch = sql[j]
                if backslash and ch == '\\':
                    j += 2
                    continue
                if ch == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            out.append(Token('string', sql[start:j], start))
            i = j
            continue
        if c == '"' or (c == '`' and dialect in BACKTICK_DIALECTS) or (c == '[' and dialect in BRACKET_DIALECTS):
            close = ']' if c == '[' else c
            j = i + 1
            while True:
                if j >= n:
                    raise SQLTextError('unterminated quoted identifier')
                if sql[j] == close:
                    if j + 1 < n and sql[j + 1] == close:
                        j += 2
                        continue
                    j += 1
                    break
                if c == '"' and dialect in BACKSLASH_DIALECTS and sql[j] == '\\':
                    j += 2
                    continue
                j += 1
            kind = 'string' if (c == '"' and dialect in ('mysql', 'bigquery', 'databricks')) else 'qident'
            out.append(Token(kind, sql[i:j], i))
            i = j
            continue
        if c == '$' and dialect in DOLLAR_DIALECTS:
            m = _DOLLAR_TAG.match(sql, i)
            if m:
                tag = m.group(0)
                end = sql.find(tag, m.end())
                if end < 0:
                    raise SQLTextError('unterminated dollar-quoted string')
                out.append(Token('string', sql[i:end + len(tag)], i))
                i = end + len(tag)
                continue
        if c == ':':
            if sql.startswith('::', i):
                out.append(Token('op', '::', i))
                i += 2
                continue
            m = _PARAM.match(sql, i)
            if m and not (out and out[-1].kind == 'op' and out[-1].text == ':'):
                out.append(Token('param', m.group(0), i))
                i = m.end()
                continue
            out.append(Token('op', ':', i))
            i += 1
            continue
        m = _WORD.match(sql, i)
        if m:
            out.append(Token('word', m.group(0), i))
            i = m.end()
            continue
        m = _NUMBER.match(sql, i)
        if m:
            out.append(Token('number', m.group(0), i))
            i = m.end()
            continue
        out.append(Token('op', c, i))
        i += 1
    return out


def code(tokens: List[Token]) -> List[Token]:
    """The tokens that are code (no whitespace or comments)."""
    return [t for t in tokens if t.kind not in ('ws', 'comment')]


def strip_trailing_semicolons(sql: str, dialect: str = '') -> str:
    """``sql`` without trailing ``;``, whitespace and comments."""
    toks = tokenize(sql, dialect)
    end = len(toks)
    while end and (toks[end - 1].kind in ('ws', 'comment') or (toks[end - 1].kind == 'op' and toks[end - 1].text == ';')):
        end -= 1
    keep_to = toks[end - 1].pos + len(toks[end - 1].text) if end else 0
    return sql[:keep_to].rstrip()


def count_statements(tokens: List[Token]) -> int:
    n, current = 0, False
    for t in code(tokens):
        if t.kind == 'op' and t.text == ';':
            if current:
                n += 1
            current = False
        else:
            current = True
    return n + (1 if current else 0)


def param_names(sql: str, dialect: str = '') -> List[str]:
    return list(dict.fromkeys(t.text[1:] for t in tokenize(sql, dialect) if t.kind == 'param'))


def bind_params(sql: str, params: Dict[str, object], style: str, dialect: str = '') -> Tuple[str, object]:
    """Rewrite ``:name`` placeholders for the driver: returns (sql, parameters).

    ``style``: ``pyformat`` (``%(name)s``; every other ``%`` doubled), ``named`` (``:name``),
    ``qmark`` (``?`` with a list in order of appearance), ``dollar`` (``$name``, DuckDB),
    ``at`` (``@name``, BigQuery). Parameters are bound by the driver; a value is never
    written into the text. Raises ValueError for a missing or unused parameter.
    """
    params = dict(params or {})
    toks = tokenize(sql, dialect)
    used = [t.text[1:] for t in toks if t.kind == 'param']
    missing = [p for p in dict.fromkeys(used) if p not in params]
    if missing:
        raise ValueError(f'no value for parameter(s): {", ".join(missing)}')
    unused = [p for p in params if p not in used]
    if unused:
        raise ValueError(f'parameter(s) not used in the SQL: {", ".join(sorted(unused))}')
    if not used:
        return sql, None
    parts: List[str] = []
    ordered: List[object] = []
    for t in toks:
        if t.kind == 'param':
            name = t.text[1:]
            if style == 'pyformat':
                parts.append(f'%({name})s')
            elif style == 'qmark':
                parts.append('?')
                ordered.append(params[name])
            elif style == 'dollar':
                parts.append(f'${name}')
            elif style == 'at':
                parts.append(f'@{name}')
            else:
                parts.append(f':{name}')
        else:
            parts.append(t.text.replace('%', '%%') if style == 'pyformat' else t.text)
    text = ''.join(parts)
    if style == 'qmark':
        return text, ordered
    return text, {k: params[k] for k in dict.fromkeys(used)}
