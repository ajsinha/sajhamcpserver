"""
SQL safety for the OLAP engines.

Every OLAP query is assembled from three kinds of caller input, and each is handled
differently:

* **Identifiers** (dataset, dimension and measure names): accepted only when the dataset
  declares them (``datasets.json``). The SQL that is interpolated is the expression the
  semantic layer configures for that name, never the caller's string.
* **Values** (filter values, date ranges): never interpolated. They are written as DuckDB
  named parameters (``$olap_f0``, ``$olap_f1_0`` ...) and bound at execution time with
  :func:`bind`. Parameter names are a pure function of the filter list, so a builder and
  the matching executor derive the same names independently.
* **Keywords and numbers** (operators, aggregations, sort directions, limits, bucket
  counts): checked against a fixed allowlist or coerced to ``int``/``float``.

Anything else raises :class:`OLAPQueryError` (a ``ValueError``) before any SQL is built.
"""

from __future__ import annotations

import datetime as _dt
import re
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

PARAM_PREFIX = "olap_"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PARAM_REF = re.compile(r"\$(" + PARAM_PREFIX + r"[A-Za-z0-9_]+)")

# operator -> SQL template; {col} is a configured expression, {p} a bound parameter
FILTER_OPERATORS = {
    "=": "{col} = {p}",
    "!=": "{col} != {p}",
    "<>": "{col} <> {p}",
    ">": "{col} > {p}",
    "<": "{col} < {p}",
    ">=": "{col} >= {p}",
    "<=": "{col} <= {p}",
    "LIKE": "{col} LIKE {p}",
    "NOT LIKE": "{col} NOT LIKE {p}",
    "ILIKE": "{col} ILIKE {p}",
    "CONTAINS": "{col} LIKE '%' || {p} || '%'",
}
_LIST_OPERATORS = {"IN", "NOT IN"}
_NULL_OPERATORS = {"IS NULL", "IS NOT NULL"}
ALLOWED_OPERATORS = set(FILTER_OPERATORS) | _LIST_OPERATORS | _NULL_OPERATORS | {"BETWEEN"}

AGGREGATIONS = {
    "SUM": "SUM({x})", "AVG": "AVG({x})", "MIN": "MIN({x})", "MAX": "MAX({x})",
    "COUNT": "COUNT({x})", "COUNT_DISTINCT": "COUNT(DISTINCT {x})", "MEDIAN": "MEDIAN({x})",
}
_SCALAR_TYPES = (str, int, float, bool, Decimal, _dt.date, _dt.datetime)
MAX_LIST_VALUES = 1000


class OLAPQueryError(ValueError):
    """A caller-supplied OLAP argument was rejected before any SQL was built."""


# ── identifiers ────────────────────────────────────────────────────────────────

def _declared_names(declared) -> Optional[set]:
    """Names a dataset declares (entries may be plain names or ``{"name": ...}`` objects).
    ``None`` when the object declares nothing at all (a duck-typed stub)."""
    if declared is None:
        return None
    names = set()
    for entry in declared:
        if isinstance(entry, str):
            names.add(entry)
        elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.add(entry["name"])
    return names


def _inline(declared, name: str) -> Optional[dict]:
    for entry in declared or []:
        if isinstance(entry, dict) and entry.get("name") == name:
            return entry
    return None


def _check_name(kind: str, name: Any, declared, dataset_name: str) -> str:
    if not isinstance(name, str) or not name:
        raise OLAPQueryError(f"{kind} name must be a non-empty string")
    allowed = _declared_names(declared)
    if allowed is None:
        if not _IDENT.match(name):
            raise OLAPQueryError(f"Invalid {kind.lower()} name: {name!r}")
        return name
    if name not in allowed:
        raise OLAPQueryError(
            f"Unknown {kind.lower()} {name!r} for dataset {dataset_name!r}. "
            f"Declared: {sorted(allowed)}")
    return name


def check_dimension(dataset, name: Any) -> str:
    return _check_name("Dimension", name, getattr(dataset, "dimensions", None),
                       getattr(dataset, "name", "?"))


def check_measure(dataset, name: Any) -> str:
    return _check_name("Measure", name, getattr(dataset, "measures", None),
                       getattr(dataset, "name", "?"))


def dimension_expr(semantic, dataset, name: Any, **kw) -> str:
    """The configured SQL expression for a declared dimension."""
    check_dimension(dataset, name)
    return semantic.resolve_dimension(name, dataset, **kw) if kw else \
        semantic.resolve_dimension(name, dataset)


def measure_expr(semantic, dataset, name: Any, aggregation: Any = None) -> str:
    """The aggregate SQL for a declared measure.

    A measure defined in ``measures.json`` (or inline in the dataset) uses its configured
    expression. A declared name with no definition is a column, aggregated with the
    (allowlisted) ``aggregation``.
    """
    check_measure(dataset, name)
    agg = aggregation_name(aggregation)
    inline = _inline(getattr(dataset, "measures", None), name)
    if inline and isinstance(inline.get("expression"), str):
        return inline["expression"]          # the dataset's own definition wins
    measure = semantic.get_measure(name)
    if measure is not None:
        return measure.expression
    return AGGREGATIONS[agg].format(x=name)


def measure_column(semantic, dataset, name: Any) -> str:
    """The un-aggregated column behind a declared measure (``SUM(amount)`` -> ``amount``)."""
    check_measure(dataset, name)
    inline = _inline(getattr(dataset, "measures", None), name)
    expr = inline.get("expression") if inline else None
    if not isinstance(expr, str):
        measure = semantic.get_measure(name)
        expr = measure.expression if measure is not None else None
    if not expr:
        return name
    if "(" in expr and ")" in expr:
        inner = expr[expr.index("(") + 1:expr.rindex(")")].strip()
        if inner.upper().startswith("DISTINCT "):
            inner = inner[9:].strip()
        return inner
    return expr


# ── keywords and numbers ───────────────────────────────────────────────────────

def aggregation_name(aggregation: Any, default: str = "SUM") -> str:
    if aggregation is None or aggregation == "":
        return default
    agg = str(aggregation).strip().upper().replace(" ", "_")
    if agg == "COUNT(DISTINCT)":
        agg = "COUNT_DISTINCT"
    if agg not in AGGREGATIONS:
        raise OLAPQueryError(f"Unsupported aggregation {aggregation!r}. Allowed: {sorted(AGGREGATIONS)}")
    return agg


def direction(value: Any, default: str = "ASC") -> str:
    if value is None or value == "":
        return default
    d = str(value).strip().upper()
    if d not in ("ASC", "DESC"):
        raise OLAPQueryError(f"Sort direction must be ASC or DESC, got {value!r}")
    return d


def integer(value: Any, name: str, minimum: int = 0, maximum: int = 1_000_000) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise OLAPQueryError(f"{name} must be an integer")
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise OLAPQueryError(f"{name} must be an integer, got {value!r}") from None
    if isinstance(value, float) and n != value:
        raise OLAPQueryError(f"{name} must be an integer, got {value!r}")
    if not minimum <= n <= maximum:
        raise OLAPQueryError(f"{name} must be between {minimum} and {maximum}, got {n}")
    return n


def number(value: Any, name: str) -> str:
    """A numeric literal for SQL (rejects anything that is not an int/float)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise OLAPQueryError(f"{name} must be a number, got {value!r}")
    f = float(value)
    if f != f or f in (float("inf"), float("-inf")):
        raise OLAPQueryError(f"{name} must be a finite number")
    return repr(int(value)) if isinstance(value, int) else repr(f)


def safe_alias(name: Any) -> str:
    safe = ''.join(c if c.isalnum() else '_' for c in str(name))
    if safe and safe[0].isdigit():
        safe = '_' + safe
    return safe or '_'


# ── values (bound, never interpolated) ─────────────────────────────────────────

def _value(v: Any, where: str) -> Any:
    if v is None or isinstance(v, _SCALAR_TYPES):
        return v
    raise OLAPQueryError(f"{where}: filter values must be strings, numbers, booleans or null")


def compile_filters(semantic, dataset, filters: Optional[Iterable[Dict[str, Any]]],
                    prefix: str = "f") -> Tuple[List[str], Dict[str, Any]]:
    """WHERE-clause fragments and the parameters they reference.

    Column expressions come from the semantic layer for declared dimensions only; every
    value is a ``$olap_<prefix><i>[_<j>]`` parameter.
    """
    clauses: List[str] = []
    params: Dict[str, Any] = {}
    if not filters:
        return clauses, params
    if not isinstance(filters, (list, tuple)):
        raise OLAPQueryError("filters must be a list of {dimension, operator, value} objects")
    for i, f in enumerate(filters):
        if not isinstance(f, dict):
            raise OLAPQueryError("each filter must be an object with dimension, operator and value")
        dim = f.get("dimension", f.get("column"))
        col = dimension_expr(semantic, dataset, dim)
        op = str(f.get("operator", "=") or "=").strip().upper()
        op = re.sub(r"\s+", " ", op)
        if op not in ALLOWED_OPERATORS:
            raise OLAPQueryError(f"Unsupported filter operator {f.get('operator')!r}. "
                                 f"Allowed: {sorted(ALLOWED_OPERATORS)}")
        val = f.get("value")
        base = f"{PARAM_PREFIX}{prefix}{i}"
        where = f"filter {i} ({dim})"
        if op in _NULL_OPERATORS:
            clauses.append(f"{col} {op}")
        elif op in _LIST_OPERATORS:
            values = list(val) if isinstance(val, (list, tuple)) else [val]
            if not values or len(values) > MAX_LIST_VALUES:
                raise OLAPQueryError(f"{where}: {op} needs 1..{MAX_LIST_VALUES} values")
            names = []
            for j, v in enumerate(values):
                params[f"{base}_{j}"] = _value(v, where)
                names.append(f"${base}_{j}")
            clauses.append(f"{col} {op} ({', '.join(names)})")
        elif op == "BETWEEN":
            if not isinstance(val, (list, tuple)) or len(val) != 2:
                raise OLAPQueryError(f"{where}: BETWEEN needs a two-element [low, high] value")
            params[f"{base}_0"] = _value(val[0], where)
            params[f"{base}_1"] = _value(val[1], where)
            clauses.append(f"{col} BETWEEN ${base}_0 AND ${base}_1")
        else:
            params[base] = _value(val, where)
            clauses.append(FILTER_OPERATORS[op].format(col=col, p=f"${base}"))
    return clauses, params


def from_clause(dataset) -> str:
    """``SELECT * FROM <source> [JOIN ...]`` from the dataset's configuration only."""
    sql = f"SELECT * FROM {dataset.source_table}"
    for join in getattr(dataset, "joins", None) or []:
        alias = f" AS {join.alias}" if join.alias else ""
        sql += f"\n{join.join_type} JOIN {join.table}{alias} ON {join.on_clause}"
    return sql


def base_query(semantic, dataset, filters, extra_clauses: Iterable[str] = ()) -> str:
    clauses, _ = compile_filters(semantic, dataset, filters)
    clauses = clauses + list(extra_clauses)
    sql = from_clause(dataset)
    if clauses:
        if getattr(dataset, "joins", None):
            # Dimension and measure expressions are written against the joined row as
            # the engines see it (a subquery, where DuckDB renames a repeated column
            # ``region`` to ``region_1``), so filters are applied over that same row,
            # not inside the join where an unqualified shared name is ambiguous.
            sql = f"SELECT * FROM (\n{sql}\n) AS _olap_src"
        sql += f"\nWHERE {' AND '.join(clauses)}"
    return sql


def filter_params(semantic, dataset, filters) -> Dict[str, Any]:
    return compile_filters(semantic, dataset, filters)[1]


def bind(sql: str, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The subset of ``params`` that ``sql`` references (DuckDB rejects unused names)."""
    if not params:
        return {}
    used = set(_PARAM_REF.findall(sql))
    return {k: v for k, v in params.items() if k in used}


def execute(conn, sql: str, params: Optional[Dict[str, Any]] = None):
    """Run ``sql`` with its bound parameters."""
    bound = bind(sql, params)
    return conn.execute(sql, bound) if bound else conn.execute(sql)


# ── caller-written SQL (duckdb_query) and catalog identifiers ──────────────────

#: Statement types a caller may run. DESCRIBE, SHOW, SUMMARIZE and PRAGMA queries
#: parse as SELECT; DDL, DML, COPY, ATTACH, SET, INSTALL/LOAD, CALL ... do not.
READ_ONLY_STATEMENT_TYPES = ("SELECT", "EXPLAIN")
_LIMIT_WORD = re.compile(r"\bLIMIT\b", re.IGNORECASE)


def read_only_sql(conn, sql: Any, limit: Optional[int] = None) -> str:
    """The text to run for a caller-written query, or :class:`OLAPQueryError`.

    DuckDB's own parser must see exactly one statement of a read-only type, checked on the
    exact text that will run (after ``LIMIT <limit>`` is appended to a row query that has
    none; it goes on its own line, so a trailing ``--`` comment cannot swallow it).
    """
    if not isinstance(sql, str) or not sql.strip():
        raise OLAPQueryError("SQL query is required")
    text = sql.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    _one_read_only_statement(conn, text)
    first = text.split(None, 1)[0].upper() if text else ""
    if limit is not None and first in ("SELECT", "WITH", "FROM") and not _LIMIT_WORD.search(text):
        text = f"{text}\nLIMIT {integer(limit, 'limit', 1, 1_000_000)}"
        _one_read_only_statement(conn, text)
    return text


def _one_read_only_statement(conn, text: str) -> None:
    try:
        statements = conn.extract_statements(text)
    except Exception as e:
        raise OLAPQueryError(f"SQL parse error: {e}") from None
    if len(statements) != 1:
        raise OLAPQueryError(f"Exactly one statement is permitted; got {len(statements)}")
    kind = str(statements[0].type).rsplit(".", 1)[-1]
    if kind not in READ_ONLY_STATEMENT_TYPES:
        raise OLAPQueryError(f"Only read-only queries are permitted. Got a {kind} statement")


def quote_identifier(name: str) -> str:
    """A double-quoted SQL identifier. Only for names read back from the catalog (or
    checked against it): the quoting makes any such name inert, not an allowlist."""
    if not isinstance(name, str) or not name or "\x00" in name:
        raise OLAPQueryError(f"Invalid identifier: {name!r}")
    return '"' + name.replace('"', '""') + '"'
