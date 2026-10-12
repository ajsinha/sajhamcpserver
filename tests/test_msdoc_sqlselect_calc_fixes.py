# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Regressions for the msdoc, sqlselect, calc, fmp and duckdb_list_files fixes:
msdoc file arguments confined to the docs folder; sqlselect sandboxed (no file access,
quoted sources, a constrained where_clause, whole-word keyword check); calc_bond_price's
face_value default; calc_currency_converter's unknown-currency error; Excel formulas as
text; fmp limit defaults equal to the schema's."""

import io
import json
import os
from pathlib import Path

import pytest

from sajha.core.storage import confined_path


# ── msdoc: path confinement ───────────────────────────────────────────────────

openpyxl = pytest.importorskip("openpyxl")
from sajha.tools.impl import msdoc_tools_tool_refactored as msdoc  # noqa: E402


def _workbook(path: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S"
    ws.append(["a", "b", "total"])
    ws.append([1, 2, "=A2+B2"])
    wb.save(path)


@pytest.fixture
def docs(tmp_path):
    root = tmp_path / "msdocs"
    root.mkdir()
    outside = tmp_path / "msd"
    outside.mkdir()
    _workbook(root / "book.xlsx")
    _workbook(outside / "sales.xlsx")
    return root, outside


def _tool(cls, root):
    return cls({"docs_directory": str(root)})


@pytest.mark.parametrize("name", ["../msd/sales.xlsx", "sub/../../msd/sales.xlsx", "..\\msd\\sales.xlsx"])
def test_msdoc_refuses_dotdot(docs, name):
    root, _ = docs
    with pytest.raises(ValueError, match="documents folder"):
        _tool(msdoc.MsDocReadExcelTool, root).execute({"filename": name})


def test_msdoc_refuses_absolute_path(docs):
    root, outside = docs
    for tool in (msdoc.MsDocReadExcelTool, msdoc.MsDocGetExcelSheetsTool, msdoc.MsDocExtractTextTool):
        with pytest.raises(ValueError, match="documents folder"):
            _tool(tool, root).execute({"filename": str(outside / "sales.xlsx")})


def test_msdoc_refuses_symlink_out_of_folder(docs):
    root, outside = docs
    (root / "link.xlsx").symlink_to(outside / "sales.xlsx")
    with pytest.raises(ValueError, match="outside the documents folder"):
        _tool(msdoc.MsDocReadExcelTool, root).execute({"filename": "link.xlsx"})
    listed = _tool(msdoc.MsDocListFilesTool, root).execute({})
    assert [f["filename"] for f in listed["files"]] == ["book.xlsx"]


def test_msdoc_reads_a_file_in_the_folder(docs):
    root, _ = docs
    r = _tool(msdoc.MsDocReadExcelTool, root).execute({"filename": "book.xlsx"})
    assert r["data"][0] == ["a", "b", "total"]


def test_confined_path_allows_inner_link_and_subfolder(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.txt").write_text("x")
    (tmp_path / "in.txt").symlink_to(tmp_path / "sub" / "x.txt")
    assert confined_path(tmp_path, "sub/x.txt") == (tmp_path / "sub" / "x.txt").resolve()
    assert confined_path(tmp_path, "in.txt") == (tmp_path / "sub" / "x.txt").resolve()
    for bad in ("", "a\0b", "/etc/passwd", "../x"):
        with pytest.raises(ValueError):
            confined_path(tmp_path, bad)


def test_msdoc_include_formulas_returns_text_not_cells(docs):
    root, _ = docs
    r = _tool(msdoc.MsDocReadExcelTool, root).execute({"filename": "book.xlsx", "include_formulas": True})
    assert r["data"][1] == [1, 2, "=A2+B2"]
    assert r["formulas"] == [[{"cell": "C2", "formula": "=A2+B2"}]]
    json.dumps(r)                      # JSON-serialisable: no openpyxl Cell objects


def test_msdoc_word_reads_with_python_docx(tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_paragraph("hello world")
    d.save(tmp_path / "w.docx")
    r = msdoc.MsDocReadWordTool({"docs_directory": str(tmp_path)}).execute({"filename": "w.docx"})
    assert r["paragraphs"] == ["hello world"]


# ── sqlselect: sandbox and SQL safety ────────────────────────────────────────

from sajha.tools.impl import sqlselect_tool_refactored as sqls  # noqa: E402


@pytest.fixture
def sql_tools(tmp_path):
    (tmp_path / "orders.csv").write_text("id,region,created_at\n1,West,2024-01-01\n2,East,2024-02-01\n3,West,2024-03-01\n")
    (tmp_path / "secret.txt").write_text("top secret\n")
    cfg = {"data_directory": str(tmp_path),
           "data_sources": {"orders": {"file": "orders.csv", "type": "csv"},
                            "odd name": {"file": "orders.csv", "type": "csv"}}}
    return {n: cls(dict(cfg, name=n)) for n, cls in sqls.SQLSELECT_TOOLS.items()}, tmp_path


@pytest.mark.parametrize("fn", ["read_text('{d}/secret.txt')", "read_csv('{d}/secret.txt')",
                                "read_csv_auto('{d}/orders.csv')"])
def test_sqlselect_query_cannot_read_files(sql_tools, fn):
    t, d = sql_tools
    r = t["sqlselect_execute_query"].execute({"query": f"SELECT * FROM {fn.format(d=d)}"})
    assert r["success"] is False
    assert "top secret" not in json.dumps(r)


def test_sqlselect_cannot_switch_access_back_on(sql_tools):
    t, _ = sql_tools
    conn = t["sqlselect_execute_query"].connection
    with pytest.raises(Exception):
        conn.execute("SET enable_external_access = true")


@pytest.mark.parametrize("sql", ["SELECT 1; DROP TABLE orders", "SELECT * FROM orders; SELECT 1"])
def test_sqlselect_query_one_read_only_statement(sql_tools, sql):
    t, _ = sql_tools
    assert t["sqlselect_execute_query"].execute({"query": sql})["success"] is False
    assert t["sqlselect_count_rows"].execute({"source_name": "orders"})["row_count"] == 3


def test_sqlselect_keyword_check_is_whole_word(sql_tools):
    t, _ = sql_tools
    r = t["sqlselect_execute_query"].execute({"query": "SELECT id, created_at FROM orders ORDER BY id"})
    assert r["success"] is True and r["row_count"] == 3
    r = t["sqlselect_execute_query"].execute({"query": "SELECT 1 AS x WHERE 1=1 OR 'a' = 'drop'"})
    assert r["success"] is False and "DROP" in r["error"]


@pytest.mark.parametrize("clause", [
    "1=1; DROP TABLE orders",
    "1=1 -- comment",
    "1=1 /* x */",
    "region = (SELECT content FROM read_text('/etc/passwd'))",
    "1=1) UNION ALL SELECT 99 WHERE (1=1",
])
def test_sqlselect_count_rows_where_clause_injection_refused(sql_tools, clause):
    t, _ = sql_tools
    r = t["sqlselect_count_rows"].execute({"source_name": "orders", "where_clause": clause})
    assert r["success"] is False
    assert t["sqlselect_count_rows"].execute({"source_name": "orders"})["row_count"] == 3


def test_sqlselect_count_rows_filter_and_quoted_source(sql_tools):
    t, _ = sql_tools
    r = t["sqlselect_count_rows"].execute({"source_name": "orders", "where_clause": "region = 'West'"})
    assert r["success"] is True and r["row_count"] == 2
    assert t["sqlselect_count_rows"].execute({"source_name": "odd name"})["row_count"] == 3
    assert t["sqlselect_sample_data"].execute({"source_name": "odd name", "limit": 1})["row_count"] == 1
    r = t["sqlselect_count_rows"].execute({"source_name": "orders; DROP TABLE orders"})
    assert r["success"] is False and "not found" in r["error"]


# ── calc ─────────────────────────────────────────────────────────────────────

from sajha.tools.impl import calc_tools  # noqa: E402


def test_bond_price_face_value_defaults_to_1000():
    t = calc_tools.CalcBondPriceTool({"name": "calc_bond_price"})
    r = t.execute({"coupon_rate": 5, "yield_rate": 5, "years": 10})
    assert r["face_value"] == 1000 and r["price"] == 1000.0


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_currency_converter_unknown_target_is_an_error(monkeypatch):
    from sajha.core import outbound
    payload = json.dumps({"result": "success", "rates": {"USD": 1, "EUR": 0.9}}).encode()
    monkeypatch.setattr(outbound, "urlopen", lambda *a, **k: _Resp(payload))
    t = calc_tools.CalcCurrencyConverterTool({"name": "calc_currency_converter"})
    r = t.execute({"from": "USD", "to": "XYZ", "amount": 10})
    assert "error" in r and "XYZ" in r["error"]
    assert t.execute({"from": "USD", "to": "EUR", "amount": 10})["converted"] == 9.0


# ── fmp: code defaults equal the schema's ────────────────────────────────────

@pytest.mark.parametrize("tool", ["market_gainers", "market_losers", "most_active", "senate_trading",
                                  "sec_filings", "price_target", "upgrades_downgrades"])
def test_fmp_limit_default_matches_schema(tool, monkeypatch):
    import importlib
    cfg = json.loads(Path(f"config/tools/fmp/fmp_{tool}.json").read_text())
    mod_name, cls_name = cfg["implementation"].rsplit(".", 1)
    cls = getattr(importlib.import_module(mod_name), cls_name)
    sent = {}
    monkeypatch.setattr(cls, "_fmp_get", lambda self, ep, params=None: sent.update(params or {}) or [],
                        raising=False)
    cls.__new__(cls).execute({"symbol": "AAPL"})
    assert sent["limit"] == cfg["inputSchema"]["properties"]["limit"]["default"]


# ── duckdb_list_files include_metadata ───────────────────────────────────────

def test_duckdb_list_files_include_metadata_false(tmp_path):
    from sajha.tools.impl import duckdb_olap_tools_refactored as dd
    (tmp_path / "a.csv").write_text("x\n1\n")
    t = dd.DuckDbListFilesTool({"name": "duckdb_list_files", "data_directory": str(tmp_path),
                                "auto_refresh_enabled": False})
    try:
        full = t.execute({})["files"][0]
        bare = t.execute({"include_metadata": False})
        assert "file_size_bytes" in full
        assert not {"file_size_bytes", "file_size_human", "modified_date"} & set(bare["files"][0])
        assert bare["summary"]["total_size_bytes"] > 0
    finally:
        with dd.DuckDbSandbox._instances_lock:
            dd.DuckDbSandbox._instances.pop(str(tmp_path.resolve()), None)
