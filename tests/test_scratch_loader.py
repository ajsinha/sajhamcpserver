# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The tool-result loader and the per-user scratch database (sajha/analytics/scratch.py;
docs/architecture/Business Intelligence.md §6, Quantitative Planners.md §3.4): rows found in tool
results, sanitised names and inferred types, provenance, one read-only SELECT only (statement
types, several statements, ATTACH, COPY, file and table functions, other catalogs), another user's
tables unreachable, row, size and time bounds, and expiry with cleanup."""

import os

import pytest

from sajha.analytics import scratch as S
from sajha.analytics.scratch import ScratchDB, ScratchError, ScratchSettings, check_select, extract_rows

SALES = {"meta": {"source": "test"},
         "rows": [{"Region": "east", "Month": "2024-01-01", "Sales": "100.5", "order": 1},
                  {"Region": "west", "Month": "2024-02-01", "Sales": ".", "order": 2},
                  {"Region": "north", "Month": "2024-03-01", "Sales": "300", "order": 3}]}


@pytest.fixture
def cfg(tmp_path):
    return ScratchSettings(dir=str(tmp_path / "scratch"), max_rows=100000, max_mb=50, max_minutes=120)


@pytest.fixture
def alice(cfg):
    return ScratchDB("alice", cfg)


# ── rows and names ───────────────────────────────────────────────

@pytest.mark.parametrize("data,path,n,first", [
    ([{"a": 1}, {"a": 2}], None, 2, {"a": 1}),
    ({"result": {"observations": [{"d": "x"}] * 3, "count": 3}}, None, 3, {"d": "x"}),
    ({"a": [{"x": 1}], "b": [{"y": 1}, {"y": 2}]}, None, 2, {"y": 1}),
    ({"a": [{"x": 1}], "b": [{"y": 1}, {"y": 2}]}, "a", 1, {"x": 1}),
    ({"a": [{"x": 1}], "b": [{"y": 1}, {"y": 2}]}, "$.b[*].y", 2, {"value": 1}),
    ({"date": ["2024-01-01", "2024-02-01"], "value": [1, 2]}, None, 2, {"date": "2024-01-01", "value": 1}),
    ({"price": 10, "symbol": "X"}, None, 1, {"price": 10, "symbol": "X"}),
    ([1, 2, 3], None, 3, {"value": 1}),
    ('[{"a": 1}]', None, 1, {"a": 1}),
])
def test_rows_are_found_in_tool_results(data, path, n, first):
    rows = extract_rows(data, path)
    assert len(rows) == n and rows[0] == first


@pytest.mark.parametrize("data,path", [("plain text", None), ({"a": [{"x": 1}]}, "$.missing"), ([], None)])
def test_no_rows_is_refused(data, path):
    with pytest.raises(ScratchError):
        extract_rows(data, path)


def test_load_sanitises_names_infers_types_and_keeps_provenance(alice):
    meta = alice.load(SALES, tool="Sales Report!", call_id="call_1", arguments={"year": 2024},
                      tool_version="2.0.0", data_classes=["internal"])
    assert meta["table"] == "sales_report" and meta["rows"] == 3
    cols = {c["name"]: (c["type"], c["source"]) for c in meta["columns"]}
    assert cols == {"region": ("VARCHAR", "Region"), "month": ("DATE", "Month"), "sales": ("DOUBLE", "Sales"),
                    "order_": ("BIGINT", "order")}
    assert meta["call_id"] == "call_1" and meta["tool"] == "Sales Report!" and meta["arguments"] == {"year": 2024}
    assert meta["tool_version"] == "2.0.0" and meta["data_classes"] == ["internal"]
    assert meta["loaded_at"] and meta["expires_at"] > meta["loaded_at"]
    again = alice.load(SALES, tool="Sales Report!", call_id="call_2")
    assert again["table"] == "sales_report_2"
    assert [t["call_id"] for t in alice.tables()] == ["call_1", "call_2"]
    out = alice.query("SELECT sum(sales) AS total, count(sales) AS n, max(month) AS last FROM sales_report")
    assert out["rows"] == [{"total": 400.5, "n": 2, "last": "2024-03-01"}] and out["tables"] == ["sales_report"]


def test_a_large_load_uses_the_bulk_path(alice):
    meta = alice.load([{"i": i, "x": i / 2} for i in range(5000)], tool="big")
    assert meta["rows"] == 5000
    assert alice.query("SELECT sum(i) AS s FROM big")["rows"] == [{"s": 12497500}]


def test_a_signed_in_user_is_needed(cfg):
    for who in (None, "", "  "):
        with pytest.raises(ScratchError):
            ScratchDB(who, cfg)


# ── one read-only SELECT ─────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "DROP TABLE sales_report",
    "DELETE FROM sales_report",
    "INSERT INTO sales_report VALUES ('x', NULL, 1, 1)",
    "UPDATE sales_report SET sales = 0",
    "CREATE TABLE x AS SELECT * FROM sales_report",
    "ATTACH 'other.duckdb' AS o",
    "COPY sales_report TO 'out.csv'",
    "SELECT 1; SELECT 2",
    "SELECT * FROM sales_report; DROP TABLE sales_report",
    "SELECT * FROM read_csv('/etc/passwd')",
    "SELECT * FROM read_parquet('x.parquet')",
    "SELECT * FROM read_json_auto('x.json')",
    "SELECT * FROM sales_report WHERE region IN (SELECT * FROM read_csv('/etc/passwd'))",
    "SELECT * FROM '/etc/hosts'",
    "SELECT * FROM glob('*')",
    "SELECT * FROM duckdb_tables()",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM other.main.sales_report",
    "SELECT * FROM _sajha_loaded",
    "PRAGMA database_list",
    "SHOW TABLES",
    "DESCRIBE sales_report",
    "EXPLAIN SELECT 1",
    "SET enable_external_access = true",
    "INSTALL httpfs",
    "",
])
def test_anything_but_one_select_over_the_loaded_tables_is_refused(alice, sql):
    alice.load(SALES, tool="sales_report")
    with pytest.raises(ScratchError):
        alice.query(sql)


def test_ctes_joins_and_subqueries_over_loaded_tables_run(alice):
    alice.load(SALES, tool="a")
    alice.load(SALES, tool="b")
    out = alice.query("WITH x AS (SELECT region, sales FROM a) SELECT x.region, b.sales FROM x JOIN b USING (region) "
                      "WHERE b.sales > (SELECT min(sales) FROM a) ORDER BY 1;")
    assert out["rows"] == [{"region": "north", "sales": 300.0}] and set(out["tables"]) == {"a", "b"}


def test_the_guard_parses_before_anything_runs():
    text, used = check_select("  SELECT * FROM t1 ;;", ["t1"])
    assert text == "SELECT * FROM t1" and used == ["t1"]
    with pytest.raises(ScratchError, match="unknown table t2"):
        check_select("SELECT * FROM t2", ["t1"])


def test_another_users_tables_are_unreachable(cfg):
    alice, bob = ScratchDB("alice", cfg), ScratchDB("bob", cfg)
    bob.load(SALES, tool="bob_secret")
    alice.load(SALES, tool="mine")
    assert alice.path != bob.path and os.path.dirname(alice.path) == cfg.dir
    with pytest.raises(ScratchError, match="unknown table bob_secret"):
        alice.query("SELECT * FROM bob_secret")
    assert [t["table"] for t in alice.tables()] == ["mine"]
    with pytest.raises(ScratchError):
        ScratchDB("carol", cfg).query("SELECT 1")          # nothing loaded


def test_a_query_can_be_limited_to_named_tables(alice):
    alice.load(SALES, tool="a")
    alice.load(SALES, tool="b")
    with pytest.raises(ScratchError, match="unknown table b"):
        alice.query("SELECT * FROM b", tables=["a"])


def test_a_bad_query_returns_duckdbs_error(alice):
    alice.load(SALES, tool="s")
    with pytest.raises(ScratchError, match="nosuch"):
        alice.query("SELECT nosuch FROM s")


# ── bounds ───────────────────────────────────────────────────────

def test_row_bound(cfg):
    db = ScratchDB("alice", ScratchSettings(dir=cfg.dir, max_rows=10, max_mb=50, max_minutes=60))
    with pytest.raises(ScratchError, match="bi.scratch_max_rows"):
        db.load([{"i": i} for i in range(11)], tool="t")
    assert db.load([{"i": i} for i in range(10)], tool="t")["rows"] == 10


def test_size_bound_leaves_nothing_behind(cfg):
    db = ScratchDB("alice", ScratchSettings(dir=cfg.dir, max_rows=100000, max_mb=1, max_minutes=60))
    db.load([{"i": 1}], tool="small")
    with pytest.raises(ScratchError, match="bi.scratch_max_mb"):
        db.load([{"i": i, "text": f"{i:08d}" + "x" * 400} for i in range(20000)], tool="big")
    assert [t["table"] for t in db.tables()] == ["small"]


def test_query_row_limit(alice):
    alice.load([{"i": i} for i in range(50)], tool="t")
    out = alice.query("SELECT i FROM t ORDER BY i", max_rows=10)
    assert out["row_count"] == 10 and out["truncated"] and out["rows"][-1] == {"i": 9}


def test_query_time_limit(alice):
    alice.load([{"i": i} for i in range(2000)], tool="t")
    with pytest.raises(ScratchError, match="longer than"):
        alice.query("SELECT count(*) FROM t a, t b, t c, t d WHERE a.i + b.i + c.i + d.i = -1", timeout_s=0.3)


def test_settings_come_from_the_bi_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("SAJHA_BI_SCRATCH_DIR", str(tmp_path / "x"))
    monkeypatch.setenv("SAJHA_BI_SCRATCH_MAX_ROWS", "7")
    monkeypatch.setenv("SAJHA_BI_SCRATCH_MAX_MB", "3")
    monkeypatch.setenv("SAJHA_BI_SCRATCH_MAX_MINUTES", "5")
    s = S.settings()
    assert (s.dir, s.max_rows, s.max_mb, s.max_minutes) == (str(tmp_path / "x"), 7, 3, 5)


# ── expiry ───────────────────────────────────────────────────────

def test_tables_expire_and_cleanup_removes_empty_files(cfg, monkeypatch):
    alice, bob = ScratchDB("alice", cfg), ScratchDB("bob", cfg)
    meta = alice.load(SALES, tool="short", ttl_minutes=1)
    long = alice.load(SALES, tool="long", ttl_minutes=100000)          # capped at max_minutes
    bob.load(SALES, tool="bobs", ttl_minutes=1)
    assert meta["expires_at"] < long["expires_at"]
    import time as _time
    later = _time.time() + 5 * 60
    monkeypatch.setattr(S, "_now", lambda: later)
    assert [t["table"] for t in alice.tables()] == ["long"]
    with pytest.raises(ScratchError, match="unknown table short"):
        alice.query("SELECT * FROM short")
    assert S.cleanup_all(cfg) == 1                                  # bob's table
    assert not os.path.exists(bob.path) and os.path.exists(alice.path)
    much_later = _time.time() + 10 * 24 * 3600
    S.cleanup_all(cfg, now=much_later)
    assert not os.path.exists(alice.path)
