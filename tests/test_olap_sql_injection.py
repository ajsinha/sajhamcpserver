"""SQL injection regressions for the OLAP tools, the semantic layer and duckdb_sql.

Filter values are bound as DuckDB parameters (a hostile value is just a value that matches
nothing); identifiers (dimensions, measures, filter columns) must be declared by the
dataset; keywords and numbers (operators, aggregations, directions, limits) are allowlisted.
See sajha/olap/sql_safety.py.
"""

import asyncio
import json

import pytest

pytest.importorskip("duckdb")

from sajha.olap import sql_safety as sq

VALUE_PAYLOADS = [
    "x' OR '1'='1",
    "North'; DROP TABLE orders; --",
    "North' -- trailing comment",
    "North' /* block */ OR /* */ '1'='1",
    "x' UNION SELECT table_name, 1, 2 FROM information_schema.tables --",
    "'); DROP TABLE customers; --",
    "$olap_f1",
]

IDENT_PAYLOADS = [
    "region; DROP TABLE orders",
    "region) UNION SELECT 1 --",
    "1=1 --",
    "region /* x */",
    "region' OR '1'='1",
    "(SELECT current_setting('threads'))",
]

FILTER_FOR = {"dimension": "region", "operator": "=", "value": None}


def _filters(value):
    return [dict(FILTER_FOR, value=value)]


# Every OLAP operation, with valid arguments on the demo data (sales_analysis).
OPERATIONS = {
    "olap_pivot_table": {"rows": ["region"], "columns": ["quarter"], "values": [{"measure": "revenue"}]},
    "olap_hierarchical_summary": {"dimensions": ["region", "product_category"],
                                  "measures": [{"measure": "revenue"}]},
    "olap_time_series": {"time_dimension": "date", "time_grain": "month", "measures": ["revenue"]},
    "olap_window_analysis": {"dimensions": ["region"], "measures": ["revenue"],
                             "calculations": [{"type": "rank", "measure": "revenue"}]},
    "olap_statistics": {"measures": ["revenue"], "group_by": ["region"]},
    "olap_histogram": {"measure": "revenue", "bins": 5},
    "olap_top_n": {"dimensions": ["product_name"], "measure": "revenue", "n": 3},
    "olap_contribution": {"dimension": "product_category", "measure": "revenue"},
    "olap_correlation": {"measures": ["revenue", "quantity"]},
    "olap_cohort_analysis": {"cohort_dimension": "order_date", "time_dimension": "order_date",
                             "entity_dimension": "customer_id", "measure": "revenue", "periods": 3},
    "olap_retention_analysis": {"cohort_dimension": "order_date", "activity_dimension": "order_date",
                                "entity_dimension": "customer_id", "periods": 3},
}

# For each operation, the argument path(s) that carry a dimension / a measure name.
DIMENSION_ARGS = {
    "olap_pivot_table": [("rows", 0), ("columns", 0)],
    "olap_hierarchical_summary": [("dimensions", 0)],
    "olap_time_series": [("time_dimension",)],
    "olap_window_analysis": [("dimensions", 0)],
    "olap_statistics": [("group_by", 0)],
    "olap_top_n": [("dimensions", 0)],
    "olap_contribution": [("dimension",)],
    "olap_cohort_analysis": [("cohort_dimension",), ("entity_dimension",)],
    "olap_retention_analysis": [("activity_dimension",), ("entity_dimension",)],
}
MEASURE_ARGS = {
    "olap_pivot_table": [("values", 0, "measure")],
    "olap_hierarchical_summary": [("measures", 0, "measure")],
    "olap_time_series": [("measures", 0)],
    "olap_window_analysis": [("measures", 0)],
    "olap_statistics": [("measures", 0)],
    "olap_histogram": [("measure",)],
    "olap_top_n": [("measure",)],
    "olap_contribution": [("measure",)],
    "olap_correlation": [("measures", 0)],
    "olap_cohort_analysis": [("measure",)],
}


@pytest.fixture(scope="module")
def olap():
    from sajha.tools.impl.duckdb_olap_advanced import DuckDBOLAPAdvancedTool
    tool = DuckDBOLAPAdvancedTool({"name": "olap_pivot_table"})

    def call(op, **overrides):
        args = json.loads(json.dumps(OPERATIONS[op]))
        args["dataset"] = "sales_analysis"
        args.update(overrides)
        return asyncio.run(tool.call_tool(op, args))

    call.tool = tool
    return call


def _set(args, path, value):
    target = args
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


def _assert_tables_intact(olap):
    tool = olap.tool
    for table in ("orders", "customers", "sales_data"):
        assert tool.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0


@pytest.mark.parametrize("op", sorted(OPERATIONS))
def test_every_operation_runs_with_valid_arguments(olap, op):
    result = olap(op, filters=[{"dimension": "region", "operator": "IN",
                                "value": ["North", "South", "East", "West"]}])
    assert result.get("success"), result


@pytest.mark.parametrize("op", sorted(OPERATIONS))
@pytest.mark.parametrize("payload", VALUE_PAYLOADS)
def test_filter_values_are_bound_not_interpolated(olap, op, payload):
    result = olap(op, filters=_filters(payload))
    assert result.get("success"), result
    sql = result.get("sql", "")
    assert payload not in sql                       # the value never reaches the SQL text
    rows = result.get("data") or []
    if op == "olap_hierarchical_summary":            # ROLLUP of nothing: one empty grand total
        assert [r["revenue"] for r in rows] == [None], rows
    elif op in ("olap_pivot_table", "olap_top_n",
              "olap_contribution", "olap_window_analysis", "olap_time_series",
              "olap_histogram", "olap_cohort_analysis", "olap_retention_analysis"):
        assert rows == [], rows                     # no region is literally named payload
    _assert_tables_intact(olap)


@pytest.mark.parametrize("op", sorted(OPERATIONS))
@pytest.mark.parametrize("payload", VALUE_PAYLOADS[:3])
def test_in_and_between_values_are_bound(olap, op, payload):
    r = olap(op, filters=[{"dimension": "region", "operator": "IN", "value": ["North", payload]}])
    assert r.get("success"), r
    assert payload not in r.get("sql", "")
    r = olap(op, filters=[{"dimension": "date", "operator": "BETWEEN", "value": [payload, payload]}])
    assert payload not in r.get("sql", "")
    _assert_tables_intact(olap)


@pytest.mark.parametrize("op", sorted(OPERATIONS))
@pytest.mark.parametrize("payload", IDENT_PAYLOADS)
def test_filter_column_must_be_a_declared_dimension(olap, op, payload):
    r = olap(op, filters=[{"dimension": payload, "operator": "=", "value": "North"}])
    assert r.get("success") is False and "Unknown dimension" in r["error"], r


@pytest.mark.parametrize("op", sorted(OPERATIONS))
@pytest.mark.parametrize("operator", ["= 'x' OR 1=1 --", "; DROP TABLE orders; --", "UNION", "=="])
def test_filter_operator_is_allowlisted(olap, op, operator):
    r = olap(op, filters=[{"dimension": "region", "operator": operator, "value": "North"}])
    assert r.get("success") is False and "Unsupported filter operator" in r["error"], r


@pytest.mark.parametrize("op,path", [(op, p) for op, ps in DIMENSION_ARGS.items() for p in ps])
@pytest.mark.parametrize("payload", IDENT_PAYLOADS)
def test_dimension_names_must_be_declared(olap, op, path, payload):
    args = json.loads(json.dumps(OPERATIONS[op]))
    _set(args, path, payload)
    r = olap(op, **args)
    assert r.get("success") is False and "Unknown dimension" in r["error"], r
    _assert_tables_intact(olap)


@pytest.mark.parametrize("op,path", [(op, p) for op, ps in MEASURE_ARGS.items() for p in ps])
@pytest.mark.parametrize("payload", IDENT_PAYLOADS)
def test_measure_names_must_be_declared(olap, op, path, payload):
    args = json.loads(json.dumps(OPERATIONS[op]))
    _set(args, path, payload)
    r = olap(op, **args)
    assert r.get("success") is False and "Unknown measure" in r["error"], r


def test_undeclared_raw_column_is_refused(olap):
    # 'amount' is a real column of sales_data, but sales_analysis does not declare it.
    r = olap("olap_pivot_table", rows=["amount"])
    assert r.get("success") is False and "Unknown dimension" in r["error"]


@pytest.mark.parametrize("op,args,message", [
    ("olap_pivot_table", {"values": [{"measure": "revenue", "aggregation": "SUM(1)); DROP TABLE orders; --"}]},
     "Unsupported aggregation"),
    ("olap_hierarchical_summary", {"measures": [{"measure": "revenue", "aggregation": "EXEC"}]},
     "Unsupported aggregation"),
    ("olap_top_n", {"n": "3; DROP TABLE orders"}, "n must be an integer"),
    ("olap_histogram", {"bins": "5) UNION SELECT 1 --"}, "bins must be an integer"),
    ("olap_cohort_analysis", {"periods": "3 OR 1=1"}, "periods must be an integer"),
    ("olap_retention_analysis", {"time_grain": "month'); DROP TABLE orders; --"}, "Unsupported time_grain"),
    ("olap_time_series", {"time_grain": "month; --"}, "Unsupported time_grain"),
    ("olap_time_series", {"comparison": {"type": "yoy'; --"}}, "Unsupported comparison"),
    ("olap_time_series", {"date_range": {"start_date": {"x": 1}}}, "date_range.start_date"),
    ("olap_top_n", {"dimensions": ["product_name"], "within_groups": ["region; --"]}, "within_groups"),
])
def test_keywords_and_numbers_are_allowlisted(olap, op, args, message):
    r = olap(op, **args)
    assert r.get("success") is False and message in r["error"], r


def test_date_range_values_are_bound(olap):
    payload = "2024-01-01' OR '1'='1"
    r = olap("olap_time_series", date_range={"start_date": payload}, fill_gaps=False)
    assert payload not in r.get("sql", "")
    _assert_tables_intact(olap)


def test_window_engine_rejects_text_defaults_and_directions():
    from types import SimpleNamespace
    from sajha.olap.window_engine import WindowCalculation, WindowEngine
    engine = WindowEngine(SimpleNamespace())
    calc = WindowCalculation(calc_type="lag", measure="revenue", default_value="0'); DROP TABLE x; --")
    with pytest.raises(sq.OLAPQueryError):
        engine._build_window_function(calc, None)
    calc = WindowCalculation(calc_type="rank", measure="revenue", order_direction="DESC; DROP TABLE x")
    with pytest.raises(sq.OLAPQueryError):
        engine._build_window_function(calc, None)


def test_semantic_layer_resolve_dimension_refuses_undeclared(olap):
    semantic = olap.tool.semantic
    dataset = semantic.get_dataset("sales_analysis")
    assert semantic.resolve_dimension("region", dataset) == "region"
    with pytest.raises(sq.OLAPQueryError):
        semantic.resolve_dimension("region; DROP TABLE orders", dataset)
    with pytest.raises(sq.OLAPQueryError):
        semantic.resolve_measure("revenue) FROM x; --")


def test_query_builder_binds_values(olap):
    from sajha.olap.query_builder import OLAPQueryBuilder
    builder = OLAPQueryBuilder(olap.tool.semantic)
    filters = [{"dimension": "region", "operator": "=", "value": "x' OR '1'='1"}]
    sql = builder.build_aggregation_query("sales_analysis", ["region"], ["revenue"], filters,
                                          sort=[{"column": "revenue", "direction": "DESC"}], limit=5)
    assert "x' OR" not in sql
    rows = sq.execute(olap.tool.conn, sql, builder.filter_params("sales_analysis", filters)).fetchall()
    assert rows == []
    with pytest.raises(sq.OLAPQueryError):
        builder.build_order_by([{"column": "revenue", "direction": "DESC; DROP TABLE orders"}])
    with pytest.raises(sq.OLAPQueryError):
        builder.build_aggregation_query("sales_analysis", ["region"], ["revenue"], limit="5; --")


# ── customer_olap_pivot (CustomerOLAPTool) ──────────────────────────────────────

@pytest.fixture(scope="module")
def customer_olap():
    from sajha.tools.impl.duckdb_olap_advanced import CustomerOLAPTool
    return CustomerOLAPTool({"name": "customer_olap_pivot"})


@pytest.mark.parametrize("payload", VALUE_PAYLOADS)
def test_customer_olap_filter_values_are_bound(customer_olap, payload):
    r = customer_olap.execute({"rows": ["region"], "measures": ["order_count"],
                               "filters": {"region": payload}})
    assert r["success"], r
    assert r["row_count"] == 0 and payload not in r["query"]
    r = customer_olap.execute({"rows": ["region"], "measures": ["order_count"],
                               "filters": {"region": ["North", payload]}})
    assert r["success"] and payload not in r["query"]


@pytest.mark.parametrize("args,message", [
    ({"filters": {"region; DROP TABLE x": "North"}}, "Unknown filter dimension"),
    ({"order_by": "region; DROP TABLE customers"}, "order_by must name"),
    ({"order_by": "-(SELECT 1)"}, "order_by must name"),
    ({"limit": "10; DROP TABLE customers"}, "limit must be an integer"),
    ({"rows": ["region) UNION SELECT 1 --"]}, "Unknown dimension"),
    ({"measures": ["SUM(1)"]}, "Unknown measure"),
])
def test_customer_olap_identifiers_and_numbers(customer_olap, args, message):
    base = {"rows": ["region"], "measures": ["order_count"]}
    base.update(args)
    r = customer_olap.execute(base)
    assert r["success"] is False and message in r["error"], r


def test_customer_olap_order_by_selected_measure_still_works(customer_olap):
    r = customer_olap.execute({"rows": ["region"], "measures": ["order_count"], "order_by": "-order_count"})
    assert r["success"], r


# ── the customer_olap dataset (olap_pivot_table / olap_time_series) ─────────────

@pytest.fixture(scope="module")
def olap_tools():
    from pathlib import Path
    from sajha.tools.impl.duckdb_olap_advanced import DuckDBOLAPAdvancedTool
    root = Path(__file__).resolve().parent.parent / "config" / "tools"
    return {n: DuckDBOLAPAdvancedTool(json.loads((root / f"{n}.json").read_text()))
            for n in ("olap_pivot_table", "olap_time_series")}


def test_customer_olap_dataset_sets_the_alias_its_joins_use():
    from sajha.olap.semantic_layer import SemanticLayer
    from pathlib import Path
    ds = SemanticLayer(str(Path(__file__).resolve().parent.parent / "config" / "olap")).datasets["customer_olap"]
    assert ds.source_table.rstrip().endswith("AS customers")
    assert [j.alias for j in ds.joins] == ["orders", "products"]


@pytest.mark.parametrize("args", [
    {"rows": ["region"], "values": [{"measure": m} for m in (
        "order_count", "customer_count", "total_revenue", "total_quantity", "avg_order_value",
        "total_discount", "total_shipping", "avg_discount_pct", "gross_profit", "profit_margin")]},
    {"rows": ["customer_segment"], "columns": ["customer_tier"], "values": [{"measure": "total_revenue"}]},
    {"rows": ["product_category"], "values": [{"measure": "customer_count"}],
     "filters": [{"dimension": "region", "operator": "IN", "value": ["North", "South"]}],
     "include_subtotals": True},
    {"rows": ["sales_rep"], "values": [{"measure": "gross_profit"}],
     "filters": [{"dimension": "product_category", "operator": "=", "value": "Electronics"}]},
])
def test_customer_olap_pivots_run(olap_tools, args):
    r = olap_tools["olap_pivot_table"].execute({"dataset": "customer_olap", **args})
    assert r["success"], r
    assert r["data"] and r["row_count"] > 0


def test_customer_olap_uses_its_own_measure_definitions(olap_tools):
    # measures.json defines total_revenue as SUM(amount); customer_olap has no amount column
    r = olap_tools["olap_pivot_table"].execute(
        {"dataset": "customer_olap", "rows": ["region"], "values": [{"measure": "total_revenue"}]})
    assert r["success"], r
    assert sum(row["total_revenue"] for row in r["data"]) > 0


def test_customer_olap_filter_on_a_shared_column_name(olap_tools):
    # product_category exists in orders and products: filtering must not be ambiguous
    everything = olap_tools["olap_pivot_table"].execute(
        {"dataset": "customer_olap", "rows": ["product_category"], "values": [{"measure": "order_count"}],
         "include_totals": False})
    one = olap_tools["olap_pivot_table"].execute(
        {"dataset": "customer_olap", "rows": ["product_category"], "values": [{"measure": "order_count"}],
         "filters": [{"dimension": "product_category", "operator": "=", "value": "Electronics"}],
         "include_totals": False})
    assert one["success"], one
    assert [row["product_category"] for row in one["data"]] == ["Electronics"]
    assert one["data"][0]["order_count"] == next(
        row["order_count"] for row in everything["data"] if row["product_category"] == "Electronics")


@pytest.mark.parametrize("payload", VALUE_PAYLOADS)
def test_customer_olap_dataset_filter_values_are_bound(olap_tools, payload):
    r = olap_tools["olap_pivot_table"].execute(
        {"dataset": "customer_olap", "rows": ["region"], "values": [{"measure": "order_count"}],
         "filters": [{"dimension": "product_category", "operator": "=", "value": payload}]})
    assert r["success"] and r["data"] == [], r


def test_customer_olap_time_series(olap_tools):
    r = olap_tools["olap_time_series"].execute(
        {"dataset": "customer_olap", "measures": ["total_revenue", "order_count"],
         "time_dimension": "order_date", "time_grain": "month",
         "date_range": {"start": "2023-01-01", "end": "2023-12-31"}})
    assert r["success"], r
    assert r["data"] and all("total_revenue" in row for row in r["data"])


# ── duckdb_sql guard rails ────────────────────────────────────────────────────────

@pytest.fixture
def duckdb_sql(tmp_path):
    from sajha.tools.impl.duckdb_olap_advanced import DuckDBSQLTool
    (tmp_path / "customers.csv").write_text("id,region\n1,North\n2,South\n")
    (tmp_path / "orders.csv").write_text("order_id,customer_id\n10,1\n11,2\n")
    return DuckDBSQLTool({"name": "duckdb_sql", "data_directory": str(tmp_path)}), tmp_path


@pytest.mark.parametrize("sql", [
    "SELECT 1; DROP TABLE orders",
    "SELECT * FROM customers; DELETE FROM customers",
    "SELECT 1 /* */ ; DROP TABLE orders --",
    "SELECT '--'; DROP TABLE orders",
    "WITH x AS (SELECT 1) INSERT INTO orders SELECT 1, 1",
    "DROP TABLE orders",
    "-- SELECT\nDROP TABLE orders",
    "/* SELECT */ DELETE FROM orders",
    "SELECT 1 UNION ALL SELECT 2; ATTACH ':memory:' AS z",
    "PRAGMA threads=1",
])
def test_duckdb_sql_refuses_anything_but_one_read_only_statement(duckdb_sql, sql):
    tool, _ = duckdb_sql
    r = tool.execute({"sql": sql})
    assert r["success"] is False, r
    assert tool.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 2


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_text('/etc/hostname')",
    "SELECT * FROM read_csv_auto('/etc/passwd')",
    "SELECT * FROM read_csv_auto('https://example.com/x.csv')",
    "SELECT current_setting('enable_external_access') AS v WHERE v",  # stays false
])
def test_duckdb_sql_has_no_file_or_network_access(duckdb_sql, sql):
    tool, _ = duckdb_sql
    r = tool.execute({"sql": sql})
    assert not r["success"] or r["row_count"] == 0, r


def test_duckdb_sql_cannot_reenable_external_access(duckdb_sql):
    tool, _ = duckdb_sql
    r = tool.execute({"sql": "SELECT 1"})
    assert r["success"]
    with pytest.raises(Exception):
        tool.conn.execute("SET enable_external_access = true")


def test_duckdb_sql_injection_in_a_literal_is_just_data(duckdb_sql):
    tool, _ = duckdb_sql
    r = tool.execute({"sql": "SELECT * FROM customers WHERE region = 'x'' OR ''1''=''1'"})
    assert r["success"] and r["row_count"] == 0, r
    r = tool.execute({"sql": "SELECT * FROM customers", "limit": "1; DROP TABLE orders"})
    assert r["success"] is False


# ── semantic layer persistence keeps placeholders ───────────────────────────────

def test_save_datasets_keeps_unresolved_placeholders(tmp_path, monkeypatch):
    from sajha.olap.semantic_layer import Dataset, SemanticLayer
    monkeypatch.setenv("SAJHA_DATA_DUCKDB_DIR", "/resolved/local/dir")
    raw = {"datasets": {"d": {
        "display_name": "D", "description": "", "dimensions": ["region"], "measures": ["amount"],
        "source_table": "read_csv_auto('${data.duckdb.dir}/a.csv')",
        "joins": [{"table": "read_csv_auto('${data.duckdb.dir}/b.csv')", "type": "LEFT",
                   "on": "a.id = b.id", "alias": "b"}]}}}
    (tmp_path / "datasets.json").write_text(json.dumps(raw))
    layer = SemanticLayer(str(tmp_path))
    ds = layer.get_dataset("d")
    assert "${" not in ds.source_table and "${" not in ds.joins[0].table   # resolved in memory

    layer.add_dataset(Dataset(name="e", display_name="E", description="", source_table="t"))
    saved = json.loads((tmp_path / "datasets.json").read_text())["datasets"]
    assert saved["d"]["source_table"] == "read_csv_auto('${data.duckdb.dir}/a.csv')"
    assert saved["d"]["joins"][0]["table"] == "read_csv_auto('${data.duckdb.dir}/b.csv')"
    assert saved["e"]["source_table"] == "t"
    assert "/resolved/local/dir" not in (tmp_path / "datasets.json").read_text()

    # A table changed in memory is saved as changed, not reverted to the old text.
    layer.datasets["d"].source_table = "other_table"
    layer._save_datasets()
    assert json.loads((tmp_path / "datasets.json").read_text())["datasets"]["d"]["source_table"] == "other_table"
