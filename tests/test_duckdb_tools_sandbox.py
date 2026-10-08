# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""SQL injection and file-access regressions for the duckdb_* tools
(sajha/tools/impl/duckdb_olap_tools_refactored.py): table and column names are looked up
in the catalog and quoted, values are bound, duckdb_query runs one read-only statement,
and the shared in-memory sandbox has external access disabled and locked."""

import pytest

from sajha.olap.sql_safety import OLAPQueryError
from sajha.tools.impl import duckdb_olap_tools_refactored as mod


@pytest.fixture
def tools(tmp_path):
    (tmp_path / "customers.csv").write_text("id,region,score\n1,North,10\n2,South,20\n3,North,30\n")
    (tmp_path / "orders.csv").write_text("order_id,customer_id,amount\n10,1,5.5\n11,2,7.0\n12,1,1.5\n")
    (tmp_path / "secret.txt").write_text("top secret\n")
    made = {name: cls({"name": name, "data_directory": str(tmp_path), "auto_refresh_enabled": False})
            for name, cls in mod.DUCKDB_TOOLS.items()}
    yield made, tmp_path
    with mod.DuckDbSandbox._instances_lock:
        mod.DuckDbSandbox._instances.pop(str(tmp_path.resolve()), None)


def _orders_intact(tools):
    t, _ = tools
    r = t["duckdb_query"].execute({"sql_query": "SELECT COUNT(*) AS n FROM orders"})
    assert r["rows"] == [{"n": 3}]


# ── duckdb_query ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE orders",
    "SELECT * FROM customers; DELETE FROM customers",
    "SELECT 1 /* */ ; DROP TABLE orders --",
    "SELECT '--'; DROP TABLE orders",
    "WITH x AS (SELECT 1) INSERT INTO orders SELECT 1, 1, 1",
    "DROP TABLE orders",
    "-- SELECT\nDROP TABLE orders",
    "CREATE TABLE t AS SELECT 1",
    "COPY orders TO 'out.csv'",
    "ATTACH ':memory:' AS z",
    "SET enable_external_access = true",
    "INSTALL httpfs",
    "PRAGMA threads=1",
    "",
])
def test_query_refuses_anything_but_one_read_only_statement(tools, sql):
    t, _ = tools
    with pytest.raises(OLAPQueryError):
        t["duckdb_query"].execute({"sql_query": sql})
    _orders_intact(tools)


@pytest.mark.parametrize("fn", [
    "read_text('{d}/secret.txt')",
    "read_csv('{d}/secret.txt')",
    "read_csv_auto('{d}/customers.csv')",
    "read_parquet('{d}/x.parquet')",
    "read_json_auto('{d}/x.json')",
    "read_blob('/etc/hostname')",
    "glob('{d}/*')",
    "read_csv_auto('https://example.com/x.csv')",
])
def test_query_cannot_read_files_or_urls(tools, fn):
    t, d = tools
    with pytest.raises(Exception) as e:
        t["duckdb_query"].execute({"sql_query": f"SELECT * FROM {fn.format(d=d)}"})
    assert "top secret" not in str(e.value)


def test_sandbox_configuration_is_locked(tools):
    t, _ = tools
    conn = t["duckdb_query"]._get_connection()
    with pytest.raises(Exception):
        conn.execute("SET enable_external_access = true")
    r = t["duckdb_query"].execute({"sql_query": "SELECT current_setting('enable_external_access') AS v"})
    assert r["rows"] == [{"v": False}]


def test_query_limit_and_comments(tools):
    t, _ = tools
    r = t["duckdb_query"].execute({"sql_query": "SELECT * FROM orders -- trailing comment", "limit": 2})
    assert r["row_count"] == 2 and r["limited"] is True
    with pytest.raises(OLAPQueryError):
        t["duckdb_query"].execute({"sql_query": "SELECT 1", "limit": "1; DROP TABLE orders"})
    r = t["duckdb_query"].execute({"sql_query": "SELECT * FROM customers WHERE region = 'x'' OR ''1''=''1'"})
    assert r["row_count"] == 0


# ── identifier-taking tools ─────────────────────────────────────────────────

BAD_TABLES = ["orders; DROP TABLE customers", "orders --", "read_text('/etc/hostname')",
              '"orders"', "main.orders", "information_schema.tables", "nope", ""]


@pytest.mark.parametrize("table", BAD_TABLES)
@pytest.mark.parametrize("tool,extra", [
    ("duckdb_describe_table", {"include_sample_data": True}),
    ("duckdb_get_stats", {}),
    ("duckdb_aggregate", {"aggregations": {"amount": "sum"}}),
    ("duckdb_refresh_views", None),
])
def test_table_names_must_be_catalog_tables(tools, table, tool, extra):
    t, _ = tools
    if extra is None and not table:
        pytest.skip("an empty view_name means every table")
    args = {"view_name": table} if extra is None else {"table_name": table, **extra}
    with pytest.raises(OLAPQueryError):
        t[tool].execute(args)
    _orders_intact(tools)


def test_table_names_are_matched_case_insensitively(tools):
    t, _ = tools
    r = t["duckdb_describe_table"].execute({"table_name": "ORDERS", "include_sample_data": True,
                                            "sample_size": 2})
    assert r["table_name"] == "orders" and r["row_count"] == 3 and len(r["sample_data"]) == 2
    with pytest.raises(OLAPQueryError):
        t["duckdb_describe_table"].execute({"table_name": "orders", "include_sample_data": True,
                                            "sample_size": "2; DROP TABLE orders"})


@pytest.mark.parametrize("columns", [
    ["amount) FROM orders; DROP TABLE orders --"], ["nope"], [1], ["*"],
])
def test_stats_columns_must_exist(tools, columns):
    t, _ = tools
    with pytest.raises(OLAPQueryError):
        t["duckdb_get_stats"].execute({"table_name": "orders", "columns": columns})
    _orders_intact(tools)


def test_stats_works(tools):
    t, _ = tools
    r = t["duckdb_get_stats"].execute({"table_name": "orders", "columns": ["AMOUNT"]})
    assert r["column_statistics"]["amount"]["count"] == 3


@pytest.mark.parametrize("args", [
    {"aggregations": {"amount); DROP TABLE orders; --": "sum"}},
    {"aggregations": {"amount": "sum(amount)); DROP TABLE orders; --"}},
    {"aggregations": {"amount": "sum"}, "group_by": ["customer_id; DROP TABLE orders"]},
    {"aggregations": {"amount": "sum"}, "group_by": ["customer_id"], "having": "1=1; DROP TABLE orders"},
    {"aggregations": {"amount": "sum"}, "group_by": ["customer_id"],
     "having": "sum_amount > 1 OR (SELECT 1) = 1"},
    {"aggregations": {"amount": "sum"}, "group_by": ["customer_id"], "having": "nope > 1"},
    {"aggregations": {"amount": "sum"}, "order_by": [{"column": "amount; DROP TABLE orders"}]},
    {"aggregations": {"amount": "sum"}, "order_by": [{"column": "sum_amount", "direction": "DESC; DROP"}]},
    {"aggregations": {"amount": "sum"}, "limit": "5; DROP TABLE orders"},
])
def test_aggregate_rejects_injection(tools, args):
    t, _ = tools
    with pytest.raises(OLAPQueryError):
        t["duckdb_aggregate"].execute({"table_name": "orders", **args})
    _orders_intact(tools)


def test_aggregate_having_values_are_bound(tools):
    t, _ = tools
    r = t["duckdb_aggregate"].execute({
        "table_name": "customers", "aggregations": {"score": "sum", "id": "count"},
        "group_by": ["region"], "having": "count_id >= 2 AND region <> 'x'' OR 1=1 --'",
        "order_by": [{"column": "sum_score", "direction": "desc"}]})
    assert r["results"] == [{"region": "North", "sum_score": 40, "count_id": 2}]


# ── sandbox lifecycle ───────────────────────────────────────────────────────

def test_tables_list_and_reload(tools):
    t, d = tools
    names = {x["name"] for x in t["duckdb_list_tables"].execute({})["tables"]}
    assert names == {"customers", "orders"}
    (d / "extra.csv").write_text("a\n1\n")
    r = t["duckdb_refresh_views"].execute({"reload_external_files": True})
    assert {v["view_name"] for v in r["refreshed_views"]} == {"customers", "orders", "extra"}
    files = {f["filename"]: f.get("is_loaded") for f in t["duckdb_list_files"].execute({})["files"]}
    assert files == {"customers.csv": True, "orders.csv": True, "extra.csv": True}
    # still sandboxed after the reload
    with pytest.raises(Exception):
        t["duckdb_query"].execute({"sql_query": f"SELECT * FROM read_text('{d}/secret.txt')"})
