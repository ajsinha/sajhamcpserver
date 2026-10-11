"""
SAJHA MCP Server — the tool-result loader and the per-user scratch database.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A tool result (a list of records, or JSON with a list of records somewhere inside it) becomes a
table in the caller's **scratch database**: one DuckDB file per user under ``bi.scratch_dir``,
never shared. Each loaded table keeps its provenance (call id, tool, arguments, time loaded) and
expires after its time to live (capped by ``bi.scratch_max_minutes``); a load is bounded by
``bi.scratch_max_rows`` rows and the database by ``bi.scratch_max_mb``.

:meth:`ScratchDB.query` runs exactly one read-only ``SELECT`` against that user's database only:
the statement is parsed (DuckDB's own parser: one statement, of type SELECT; its syntax tree may
name only the loaded tables and CTEs, no table functions such as ``read_csv``, no other catalog),
and it runs on a read-only connection with file access disabled and locked (no ATTACH, COPY or
file reads), with a row limit and a time limit.

Used by the ``data_analyst`` planner (docs/architecture/Quantitative Planners.md §3.4) and, later,
Business Intelligence's ``bi_load_tool_result`` (docs/architecture/Business Intelligence.md §6).
"""

from __future__ import annotations

import datetime as _dt
import decimal
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

META = "_sajha_loaded"                 # the provenance table in every scratch database
MAX_COLUMNS = 200
DEFAULT_TTL_MINUTES = 60
DEFAULT_QUERY_ROWS = 1000
DEFAULT_QUERY_SECONDS = 10.0
_IDENT_MAX = 60
_NULL_TEXT = {"", ".", "na", "n/a", "nan", "null", "none", "-"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$")
_NUMERIC = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
# table references a query may contain (DuckDB's json_serialize_sql "from_table" types)
_TABLE_REFS = {"BASE_TABLE", "JOIN", "SUBQUERY", "EMPTY", "EXPRESSION_LIST"}
_FIRST_WORDS = {"SELECT", "WITH", "FROM", "("}


class ScratchError(ValueError):
    """A load or a query was refused (bounds, a statement that is not one read-only SELECT, ...)."""


# ── settings ─────────────────────────────────────────────────────

@dataclass
class ScratchSettings:
    """``bi.scratch_*`` (env ``SAJHA_BI_SCRATCH_<FIELD>`` > YAML > these defaults)."""
    dir: str = "data/bi/scratch"
    max_rows: int = 100_000
    max_mb: int = 100
    max_minutes: int = 240

    @classmethod
    def load(cls) -> "ScratchSettings":
        from sajha.core.config import _get, _int
        d = cls()
        return cls(dir=_get("bi.scratch_dir", d.dir) or d.dir,
                   max_rows=max(1, _int("bi.scratch_max_rows", d.max_rows)),
                   max_mb=max(1, _int("bi.scratch_max_mb", d.max_mb)),
                   max_minutes=max(1, _int("bi.scratch_max_minutes", d.max_minutes)))


def settings() -> ScratchSettings:
    return ScratchSettings.load()


# ── names ────────────────────────────────────────────────────────

_RESERVED: Optional[Set[str]] = None


def _reserved() -> Set[str]:
    global _RESERVED
    if _RESERVED is None:
        import duckdb
        con = duckdb.connect()
        try:
            _RESERVED = {r[0].lower() for r in con.execute(
                "SELECT keyword_name FROM duckdb_keywords() WHERE keyword_category <> 'unreserved'").fetchall()}
        finally:
            con.close()
    return _RESERVED


def sanitize_identifier(name: Any, fallback: str = "t") -> str:
    """A lower-case identifier the model can write unquoted: [a-z_][a-z0-9_]*, not a keyword."""
    s = re.sub(r"[^a-z0-9_]+", "_", str(name or "").strip().lower()).strip("_")
    s = re.sub(r"_+", "_", s)[:_IDENT_MAX] or fallback
    if s[0].isdigit():
        s = f"{fallback}_{s}"[:_IDENT_MAX]
    if s.startswith("_sajha") or s.startswith("sajha_loaded"):
        s = f"{fallback}{s}"[:_IDENT_MAX]
    if s in _reserved():
        s = f"{s}_"
    return s


def _unique(base: str, taken: Iterable[str]) -> str:
    have = {t.lower() for t in taken}
    if base not in have:
        return base
    k = 2
    while f"{base[:_IDENT_MAX - 4]}_{k}" in have:
        k += 1
    return f"{base[:_IDENT_MAX - 4]}_{k}"


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# ── rows out of a tool result ────────────────────────────────────

def _is_records(v: Any) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v[:50])


def _find_records(v: Any, depth: int = 0) -> Optional[List[Any]]:
    """The largest list of objects within three levels of ``v``."""
    best: Optional[List[Any]] = None
    if _is_records(v):
        return v
    if depth >= 3:
        return None
    children = list(v.values()) if isinstance(v, dict) else (v if isinstance(v, list) else [])
    for c in children:
        if isinstance(c, (dict, list)):
            hit = _find_records(c, depth + 1)
            if hit is not None and (best is None or len(hit) > len(best)):
                best = hit
    return best


def _columnar(d: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """{col: [values], ...} with equal lengths -> records."""
    lists = {k: v for k, v in d.items() if isinstance(v, list)}
    if len(lists) < 2 or len(lists) != len(d):
        return None
    n = {len(v) for v in lists.values()}
    if len(n) != 1 or not next(iter(n)):
        return None
    if any(isinstance(x, (dict, list)) for v in lists.values() for x in v[:20]):
        return None
    return [{k: lists[k][i] for k in lists} for i in range(next(iter(n)))]


def extract_rows(data: Any, rows_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """The rows of a tool result: at ``rows_path`` (a JSONPath such as ``$.observations`` or a
    dotted path ``observations``) when given, else the largest list of records in it, else a
    columnar object, else a flat object as one row. Scalars in a list become ``{"value": x}``."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            raise ScratchError("the tool result is text, not JSON with rows") from None
    if rows_path:
        from sajha.quality.jsonpath import JSONPathError, find
        path = rows_path.strip()
        if not path.startswith("$"):
            path = "$." + path.lstrip(".")
        try:
            hits = find(data, path)
        except JSONPathError as e:
            raise ScratchError(f"rows_path: {e}") from None
        if not hits:
            raise ScratchError(f"rows_path {rows_path} matches nothing in the result")
        rows: Any = hits[0] if len(hits) == 1 and isinstance(hits[0], list) else hits
    else:
        rows = _find_records(data)
        if rows is None and isinstance(data, dict):
            inner = data.get("result") if isinstance(data.get("result"), dict) else data
            rows = _columnar(inner)
            if rows is None and inner and all(not isinstance(v, list) for v in inner.values()):
                rows = [inner]
        if rows is None and isinstance(data, list):
            rows = data
    if not isinstance(rows, list) or not rows:
        raise ScratchError("no rows found in the tool result (give rows_path)")
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append(r)
        elif isinstance(r, list):
            out.append({f"c{i + 1}": v for i, v in enumerate(r)})
        else:
            out.append({"value": r})
    return out


# ── column types ─────────────────────────────────────────────────

def _infer(values: List[Any]) -> str:
    vals = [v for v in values if v is not None]
    if not vals:
        return "VARCHAR"
    if all(isinstance(v, bool) for v in vals):
        return "BOOLEAN"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
        return "BIGINT" if all(-(2 ** 63) < v < 2 ** 63 for v in vals) else "DOUBLE"
    if all(isinstance(v, (int, float, decimal.Decimal)) and not isinstance(v, bool) for v in vals):
        return "DOUBLE"
    if all(isinstance(v, str) for v in vals):
        text = [v.strip() for v in vals]
        real = [t for t in text if t.lower() not in _NULL_TEXT]
        if real and all(_NUMERIC.match(t) for t in real):
            return "DOUBLE"
        if real and all(_DATE.match(t) for t in real) and len(real) == len(text):
            return "DATE"
        if real and all(_DATETIME.match(t) for t in real) and len(real) == len(text):
            return "TIMESTAMP"
    return "VARCHAR"


def _convert(v: Any, typ: str) -> Any:
    if v is None:
        return None
    if typ == "DOUBLE":
        if isinstance(v, str):
            t = v.strip()
            return None if t.lower() in _NULL_TEXT else float(t)
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if typ == "DATE":
        return _dt.date.fromisoformat(v.strip())
    if typ == "TIMESTAMP":
        return _dt.datetime.fromisoformat(v.strip().replace(" ", "T"))
    if typ in ("BIGINT", "BOOLEAN"):
        return v
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str, ensure_ascii=False)
    return str(v)


def _plain(v: Any) -> Any:
    """A query value as JSON-safe data."""
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (_dt.date, _dt.datetime, _dt.time)):
        return v.isoformat()
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    return str(v)


# ── the statement guard ──────────────────────────────────────────

def _walk(node: Any, refs: List[Dict[str, Any]], ctes: Set[str]) -> None:
    if isinstance(node, dict):
        if "type" in node and "sample" in node and "class" not in node and "query_location" in node:
            refs.append(node)
        cmap = node.get("cte_map")
        if isinstance(cmap, dict):
            for m in cmap.get("map") or []:
                if isinstance(m, dict) and m.get("key"):
                    ctes.add(str(m["key"]).lower())
        for v in node.values():
            _walk(v, refs, ctes)
    elif isinstance(node, list):
        for v in node:
            _walk(v, refs, ctes)


def check_select(sql: Any, allowed_tables: Iterable[str]) -> Tuple[str, List[str]]:
    """``(text, tables)`` for one read-only SELECT over ``allowed_tables`` (and its own CTEs), or
    :class:`ScratchError`. ``text`` has trailing semicolons removed; ``tables`` lists the loaded
    tables it reads."""
    import duckdb
    if not isinstance(sql, str) or not sql.strip():
        raise ScratchError("the query is empty")
    text = sql.strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    head = re.sub(r"^(\s|--[^\n]*\n|/\*.*?\*/)+", "", text, flags=re.S)
    first = "(" if head.startswith("(") else (head.split(None, 1)[0].upper() if head else "")
    if first not in _FIRST_WORDS:
        raise ScratchError(f"only a SELECT is allowed; the statement starts with {first or 'nothing'}")
    con = duckdb.connect(config={"enable_external_access": False, "autoload_known_extensions": False,
                                 "autoinstall_known_extensions": False})
    try:
        try:
            statements = con.extract_statements(text)
        except Exception as e:
            raise ScratchError(f"SQL parse error: {e}") from None
        if len(statements) != 1:
            raise ScratchError(f"exactly one statement is allowed; got {len(statements)}")
        kind = str(statements[0].type).rsplit(".", 1)[-1]
        if kind != "SELECT":
            raise ScratchError(f"only a SELECT is allowed; got a {kind} statement")
        raw = con.execute("SELECT json_serialize_sql($1)", [text]).fetchone()[0]
    finally:
        con.close()
    tree = json.loads(raw)
    if tree.get("error"):
        raise ScratchError(f"SQL parse error: {tree.get('error_message') or 'not a plain SELECT'}")
    refs: List[Dict[str, Any]] = []
    ctes: Set[str] = set()
    _walk(tree.get("statements"), refs, ctes)
    allowed = {t.lower() for t in allowed_tables}
    used: List[str] = []
    for r in refs:
        typ = r.get("type")
        if typ == "TABLE_FUNCTION":
            fn = ((r.get("function") or {}).get("function_name")) or "a table function"
            raise ScratchError(f"{fn}: table functions (read_csv, read_parquet, ...) are not allowed")
        if typ not in _TABLE_REFS:
            raise ScratchError(f"{str(typ).lower()} is not allowed in a query")
        if typ != "BASE_TABLE":
            continue
        cat, sch, name = r.get("catalog_name") or "", r.get("schema_name") or "", str(r.get("table_name") or "")
        if cat or sch not in ("", "main"):
            raise ScratchError(f"{'.'.join(x for x in (cat, sch, name) if x)}: only the loaded tables can be read")
        low = name.lower()
        if low in ctes and not sch:
            continue
        if low not in allowed:
            shown = ", ".join(sorted(allowed)) or "none"
            raise ScratchError(f"unknown table {name} (loaded tables: {shown})")
        if low not in used:
            used.append(low)
    return text, used


# ── the per-user database ────────────────────────────────────────

_LOCKS: Dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_last_cleanup = [0.0]


def _now() -> float:
    return time.time()


def _lock_for(path: str) -> threading.RLock:
    with _LOCKS_GUARD:
        lk = _LOCKS.get(path)
        if lk is None:
            lk = _LOCKS[path] = threading.RLock()
        return lk


def user_file(user_id: str, s: ScratchSettings) -> str:
    digest = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:32]
    return os.path.join(s.dir, f"u_{digest}.duckdb")


def _connect(path: str, read_only: bool = False, tries: int = 20):
    """A connection to ``path``; read-only connections cannot reach files or change that."""
    import duckdb
    cfg: Dict[str, Any] = {"autoload_known_extensions": False, "autoinstall_known_extensions": False}
    if read_only:
        cfg.update(enable_external_access=False, threads=2, lock_configuration=True)
    last: Optional[Exception] = None
    for i in range(tries):
        try:
            return duckdb.connect(path, read_only=read_only, config=cfg)
        except duckdb.IOException as e:      # another process holds the file lock
            last = e
            time.sleep(min(0.05 * (i + 1), 0.25))
    raise ScratchError(f"the scratch database is busy: {last}")


def _ensure_meta(con) -> None:
    con.execute(f"CREATE TABLE IF NOT EXISTS {META} (table_name VARCHAR PRIMARY KEY, call_id VARCHAR, "
                "tool VARCHAR, tool_version VARCHAR, arguments VARCHAR, rows_path VARCHAR, row_count BIGINT, "
                "columns VARCHAR, data_classes VARCHAR, loaded_at DOUBLE, expires_at DOUBLE)")


def _sweep(con, now: Optional[float] = None) -> List[str]:
    """Drop expired tables (and tables with no provenance row). Returns the dropped names."""
    now = _now() if now is None else now
    dropped = [r[0] for r in con.execute(f"SELECT table_name FROM {META} WHERE expires_at <= ?", [now]).fetchall()]
    known = {r[0] for r in con.execute(f"SELECT table_name FROM {META}").fetchall()}
    present = [r[0] for r in con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE database_name = current_database() AND schema_name = 'main'"
    ).fetchall()]
    dropped += [t for t in present if t != META and t not in known]
    for t in dropped:
        con.execute(f"DROP TABLE IF EXISTS {_q(t)}")
        con.execute(f"DELETE FROM {META} WHERE table_name = ?", [t])
    return dropped


def _row_meta(r: Sequence[Any]) -> Dict[str, Any]:
    (name, call_id, tool, version, args, rows_path, n, cols, classes, loaded, expires) = r
    return {"table": name, "call_id": call_id, "tool": tool, "tool_version": version or "",
            "arguments": json.loads(args or "{}"), "rows_path": rows_path or "", "rows": int(n or 0),
            "columns": json.loads(cols or "[]"), "data_classes": json.loads(classes or "[]"),
            "loaded_at": _iso(loaded), "expires_at": _iso(expires)}


def _iso(t: Optional[float]) -> Optional[str]:
    if t is None:
        return None
    return _dt.datetime.fromtimestamp(float(t), _dt.timezone.utc).isoformat(timespec="seconds")


class ScratchDB:
    """One user's scratch database (a DuckDB file under ``bi.scratch_dir``)."""

    def __init__(self, user_id: Optional[str], cfg: Optional[ScratchSettings] = None):
        if not user_id or not str(user_id).strip():
            raise ScratchError("a scratch database needs a signed-in user")
        self.user_id = str(user_id)
        self.settings = cfg or settings()
        self.path = user_file(self.user_id, self.settings)
        self._lock = _lock_for(os.path.abspath(self.path))

    # loading
    def load(self, data: Any, *, tool: str, call_id: str = "", arguments: Optional[Dict[str, Any]] = None,
             rows_path: Optional[str] = None, table: Optional[str] = None, ttl_minutes: Optional[float] = None,
             tool_version: str = "", data_classes: Optional[List[str]] = None) -> Dict[str, Any]:
        """Load the rows of ``data`` as a new table; returns its provenance (``table``, ``rows``,
        ``columns`` [{name, type, source}], ``call_id``, ``tool``, ``arguments``, ``loaded_at``,
        ``expires_at``). Raises :class:`ScratchError` when a bound is exceeded."""
        s = self.settings
        rows = extract_rows(data, rows_path)
        if len(rows) > s.max_rows:
            raise ScratchError(f"{len(rows)} rows is more than bi.scratch_max_rows ({s.max_rows})")
        keys: List[str] = []
        seen: Set[str] = set()
        for r in rows:
            for k in r:
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        if len(keys) > MAX_COLUMNS:
            raise ScratchError(f"{len(keys)} columns is more than {MAX_COLUMNS}")
        names: List[str] = []
        for k in keys:
            names.append(_unique(sanitize_identifier(k, "c"), names))
        types = [_infer([r.get(k) for r in rows]) for k in keys]
        columns = [{"name": n, "type": t, "source": str(k)} for n, t, k in zip(names, types, keys)]
        try:
            values = [tuple(_convert(r.get(k), t) for k, t in zip(keys, types)) for r in rows]
        except (TypeError, ValueError) as e:
            raise ScratchError(f"a value could not be converted: {e}") from None
        ttl = min(float(ttl_minutes or DEFAULT_TTL_MINUTES), float(s.max_minutes))
        ttl = max(ttl, 1.0 / 60)
        now = _now()
        maybe_cleanup(s)
        os.makedirs(s.dir, exist_ok=True)
        with self._lock:
            con = _connect(self.path)
            try:
                _ensure_meta(con)
                _sweep(con, now)
                taken = [r[0] for r in con.execute(
                    "SELECT table_name FROM duckdb_tables() WHERE database_name = current_database()").fetchall()]
                name = _unique(sanitize_identifier(table or tool, "t"), taken + [META])
                cols_sql = ", ".join(f"{_q(n)} {t}" for n, t in zip(names, types))
                con.execute(f"CREATE TABLE {_q(name)} ({cols_sql})")
                try:
                    self._insert(con, name, names, types, values)
                    con.execute(f"INSERT INTO {META} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                [name, call_id or "", tool, tool_version or "",
                                 json.dumps(arguments or {}, default=str, sort_keys=True), rows_path or "",
                                 len(rows), json.dumps(columns), json.dumps(list(data_classes or [])),
                                 now, now + ttl * 60])
                    con.execute("CHECKPOINT")
                    used = self._used_bytes(con)
                    if used > s.max_mb * 1024 * 1024:
                        raise ScratchError(f"the scratch database would hold {used / 1048576:.1f} MB, more than "
                                           f"bi.scratch_max_mb ({s.max_mb})")
                except BaseException:
                    con.execute(f"DROP TABLE IF EXISTS {_q(name)}")
                    con.execute(f"DELETE FROM {META} WHERE table_name = ?", [name])
                    con.execute("CHECKPOINT")
                    raise
                row = con.execute(f"SELECT * FROM {META} WHERE table_name = ?", [name]).fetchone()
            finally:
                con.close()
        return _row_meta(row)

    @staticmethod
    def _insert(con, name: str, names: List[str], types: List[str], values: List[tuple]) -> None:
        if not values:
            return
        try:
            import pandas as pd
        except Exception:
            pd = None
        if pd is not None and len(values) > 200:
            df = pd.DataFrame.from_records(values, columns=[f"c{i}" for i in range(len(names))])
            con.register("_sajha_src", df)
            try:
                casts = ", ".join(f"CAST(c{i} AS {t})" for i, t in enumerate(types))
                con.execute(f"INSERT INTO {_q(name)} SELECT {casts} FROM _sajha_src")
            finally:
                con.unregister("_sajha_src")
            return
        marks = ", ".join("?" for _ in names)
        con.executemany(f"INSERT INTO {_q(name)} VALUES ({marks})", [list(v) for v in values])

    @staticmethod
    def _used_bytes(con) -> int:
        r = con.execute("SELECT used_blocks * block_size FROM pragma_database_size() "
                        "WHERE database_name = current_database()").fetchone()
        return int(r[0] or 0) if r else 0

    # reading
    def tables(self) -> List[Dict[str, Any]]:
        """The live tables with their provenance (expired ones are dropped first)."""
        if not os.path.exists(self.path):
            return []
        with self._lock:
            con = _connect(self.path)
            try:
                _ensure_meta(con)
                _sweep(con)
                rows = con.execute(f"SELECT * FROM {META} ORDER BY loaded_at").fetchall()
            finally:
                con.close()
        return [_row_meta(r) for r in rows]

    def query(self, sql: str, *, tables: Optional[Iterable[str]] = None, max_rows: Optional[int] = None,
              timeout_s: Optional[float] = None) -> Dict[str, Any]:
        """Run one read-only SELECT over this user's live tables (only ``tables`` when given).
        Returns ``{sql, columns, rows, row_count, truncated, tables, ms}``."""
        import duckdb
        limit = max(1, int(max_rows or DEFAULT_QUERY_ROWS))
        timeout = max(0.1, float(timeout_s or DEFAULT_QUERY_SECONDS))
        if not os.path.exists(self.path):
            raise ScratchError("nothing is loaded in the scratch database")
        with self._lock:
            live = {t["table"] for t in self.tables()}
            allowed = live if tables is None else live & {str(t).lower() for t in tables}
            text, used = check_select(sql, allowed)
            con = _connect(self.path, read_only=True)
            timer = threading.Timer(timeout, con.interrupt)
            t0 = time.time()
            try:
                timer.start()
                cur = con.execute(text)
                columns = [d[0] for d in cur.description or []]
                fetched = cur.fetchmany(limit + 1)
            except duckdb.InterruptException:
                raise ScratchError(f"the query ran longer than {timeout:g} s and was stopped") from None
            except duckdb.Error as e:
                if time.time() - t0 >= timeout:
                    raise ScratchError(f"the query ran longer than {timeout:g} s and was stopped") from None
                raise ScratchError(str(e).strip()[:1000]) from None
            finally:
                timer.cancel()
                con.close()
        rows = [{c: _plain(v) for c, v in zip(columns, r)} for r in fetched[:limit]]
        return {"sql": text, "columns": columns, "rows": rows, "row_count": len(rows),
                "truncated": len(fetched) > limit, "tables": used, "ms": int((time.time() - t0) * 1000)}

    def drop(self, table: str) -> bool:
        if not os.path.exists(self.path):
            return False
        with self._lock:
            con = _connect(self.path)
            try:
                _ensure_meta(con)
                hit = con.execute(f"SELECT 1 FROM {META} WHERE table_name = ?", [table]).fetchone()
                if hit:
                    con.execute(f"DROP TABLE IF EXISTS {_q(table)}")
                    con.execute(f"DELETE FROM {META} WHERE table_name = ?", [table])
            finally:
                con.close()
        return bool(hit)


# ── cleanup ──────────────────────────────────────────────────────

def cleanup_all(cfg: Optional[ScratchSettings] = None, now: Optional[float] = None) -> int:
    """Sweep every scratch database under ``bi.scratch_dir``: drop expired tables and delete files
    left with none. Returns the number of tables dropped."""
    s = cfg or settings()
    if not os.path.isdir(s.dir):
        return 0
    dropped = 0
    for fn in sorted(os.listdir(s.dir)):
        if not (fn.startswith("u_") and fn.endswith(".duckdb")):
            continue
        path = os.path.join(s.dir, fn)
        with _lock_for(os.path.abspath(path)):
            try:
                con = _connect(path, tries=1)
            except ScratchError:
                continue                    # in use by another process: next time
            try:
                _ensure_meta(con)
                dropped += len(_sweep(con, now))
                left = con.execute(f"SELECT count(*) FROM {META}").fetchone()[0]
            finally:
                con.close()
            if not left:
                for p in (path, path + ".wal"):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
    return dropped


def maybe_cleanup(cfg: Optional[ScratchSettings] = None, every_s: float = 60.0) -> None:
    """:func:`cleanup_all` at most once a minute per process (called on every load)."""
    if time.time() - _last_cleanup[0] < every_s:
        return
    _last_cleanup[0] = time.time()
    try:
        cleanup_all(cfg)
    except Exception as e:
        logger.debug(f"scratch cleanup: {e}")
