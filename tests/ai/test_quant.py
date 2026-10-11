# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The quantitative workspace (sajha/ai/quant; docs/architecture/Quantitative Planners.md §2): units
and their conversions, known answers and unit refusals for every operation of the library, the
workspace (names, lineage, JSON), the ai.quant settings, and agreement with the calc_* tools."""

import json
import math

import pytest

from sajha.ai.quant import (Quantity, QuantError, Unit, UnitError, Workspace, convertible, equivalents, operation,
                            operations, ops, parse_unit, set_quant_settings, workspace_of)
from sajha.ai.quant.settings import QuantSettings, load_settings
from tests.ai.conftest import ToolBox


@pytest.fixture(autouse=True)
def default_settings():
    set_quant_settings(QuantSettings())
    yield
    set_quant_settings(None)


def Q(v, u=None, **kw):
    return Quantity.of(v, u, **kw)


def approx(x, rel=1e-9, abs_=1e-9):
    return pytest.approx(x, rel=rel, abs=abs_)


# ── units (§2.2) ─────────────────────────────────────────────────

@pytest.mark.parametrize("text,kind,code,scale", [
    ("USD", "currency", "USD", ""), ("usd mn", "currency", "USD", "mn"), ("EUR billion", "currency", "EUR", "bn"),
    ("GBP k", "currency", "GBP", "k"), ("JPY tn", "currency", "JPY", "tn"), ("%", "percent", "", ""),
    ("percent", "percent", "", ""), ("bp", "bp", "", ""), ("bps", "bp", "", ""), ("basis points", "bp", "", ""),
    ("pp", "pp", "", ""), ("percentage points", "pp", "", ""), ("ratio", "ratio", "", ""),
    ("count", "count", "", ""), ("count mn", "count", "", "mn"), ("index", "index", "", ""),
    ("index points", "index", "", ""), ("days", "days", "", ""), ("years", "years", "", ""),
    ("", "unitless", "", ""), ("unitless", "unitless", "", ""), ("USD/EUR", "per", "USD/EUR", ""),
])
def test_units_parse(text, kind, code, scale):
    u = parse_unit(text)
    assert (u.kind, u.code, u.scale) == (kind, code, scale)
    assert parse_unit(str(u)) == u


@pytest.mark.parametrize("bad", ["furlongs", "percent mn", "USD/EUR/GBP", "index k", 5])
def test_unknown_units_are_refused(bad):
    with pytest.raises(UnitError):
        parse_unit(bad)


def test_allowed_conversions():
    assert Q(45, "bp").to("percent").value == approx(0.45)
    assert Q(45, "bp").to("ratio").value == approx(0.0045)
    assert Q(1, "percent").to("bp").value == approx(100)
    assert Q(0.01, "ratio").to("percent").value == approx(1)
    assert Q(1.5, "USD bn").to("USD mn").value == approx(1500)
    assert Q(2500, "USD").to("USD k").value == approx(2.5)
    assert Q(3, "count mn").to("count").value == approx(3e6)
    assert Q(730, "days").to("years").value == approx(2)
    assert Q(0.5, "years").to("days").value == approx(182.5)
    assert Q([1, 2], "percent").to("bp").value == [approx(100), approx(200)]


def test_day_count_basis_from_settings():
    set_quant_settings(QuantSettings(day_count="act/360"))
    assert Q(360, "days").to("years").value == approx(1)
    assert Q(360, "days").to("years", day_count="act/365").value == approx(360 / 365)


@pytest.mark.parametrize("src,dst,code", [("USD", "EUR", "cross_currency"), ("USD mn", "GBP", "cross_currency"),
                                          ("USD", "percent", "level_rate"), ("bp", "count", "level_rate"),
                                          ("index", "percent", "level_rate"), ("days", "USD", "unit"),
                                          ("index", "count", "unit"), ("unitless", "ratio", "unit")])
def test_refused_conversions(src, dst, code):
    with pytest.raises(UnitError) as e:
        Q(1, src).to(dst)
    assert e.value.code == code and str(e.value)
    assert not convertible(src, dst)


def test_cross_currency_refusal_says_what_to_do():
    with pytest.raises(UnitError, match="fx_convert"):
        Q(1, "USD").to("EUR")


def test_equivalents():
    assert {str(u) for u in equivalents("bp")} == {"bp", "percent", "pp", "ratio"}
    assert str(equivalents("USD mn")[0]) == "USD mn" and len(equivalents("USD mn")) == 5
    assert equivalents("index") == [Unit("index")]


# ── quantities ───────────────────────────────────────────────────

def test_quantity_values_are_checked():
    assert Q("1,234.5", "USD").value == 1234.5
    for bad in ["abc", float("nan"), float("inf"), [[1, 2], [3]], True]:
        with pytest.raises(QuantError):
            Q(bad)


def test_max_table_cells():
    set_quant_settings(QuantSettings(max_table_cells=4))
    Q([1, 2, 3, 4])
    with pytest.raises(QuantError, match="max_table_cells"):
        Q([1, 2, 3, 4, 5])
    with pytest.raises(QuantError, match="max_table_cells"):
        Q([[1, 2, 3], [4, 5, 6]])


def test_from_tool_records_its_source():
    q = Quantity.from_tool(310.3, "index", call_id="c1", tool="fred_cpi", path="$.data[0].value",
                           arguments={"limit": 13}, as_of="2026-09")
    assert q.source == {"kind": "tool", "call_id": "c1", "tool": "fred_cpi", "version": "",
                        "arguments": {"limit": 13}, "path": "$.data[0].value", "unit_from": "declared"}
    assert q.as_of == "2026-09" and q.lineage is None


# ── the operation library (§2.3): known answers ──────────────────

def test_every_operation_of_the_design_exists():
    assert set(operations()) == {"diff", "pp", "pct_change", "ratio", "bp_spread", "cagr", "annualise", "npv", "irr",
                                 "weighted_avg", "sum", "mean", "median", "stdev", "min", "max", "regression",
                                 "correlation", "convert", "fx_convert", "round"}
    with pytest.raises(QuantError, match="no operation"):
        operation("divide")


def test_diff():
    r = ops.diff(Q(5, "USD mn"), Q(2_000_000, "USD"))
    assert r.value == approx(3) and str(r.unit) == "USD mn"
    r = ops.diff(Q(4.10, "percent"), Q(2.65, "percent"))
    assert r.value == approx(1.45) and str(r.unit) == "pp"
    r = ops.diff(Q(4.10, "percent"), Q(265, "bp"))
    assert r.value == approx(1.45) and str(r.unit) == "pp"
    assert str(ops.diff(Q(4.1, "percent"), Q(0.5, "pp")).unit) == "percent"
    assert ops.diff(Q(30, "bp"), Q(10, "bp")).value == approx(20)
    assert ops.diff(Q(2, "years"), Q(365, "days")).value == approx(1)
    assert ops.diff(Q([3, 5], "count"), Q([1, 1], "count")).value == [2, 4]
    assert ops.diff(Q(110, "index"), Q(100, "index")).value == approx(10)


@pytest.mark.parametrize("a,b", [((1, "USD"), (1, "EUR")), ((1, "USD"), (1, "percent")), ((1, "index"), (1, "count")),
                                 ((1, "USD"), (1, "unitless"))])
def test_diff_refuses_mixed_units(a, b):
    with pytest.raises(UnitError):
        ops.diff(Q(*a), Q(*b))


def test_diff_refuses_columns_of_different_length():
    with pytest.raises(QuantError, match="different lengths"):
        ops.diff(Q([1, 2], "USD"), Q([1, 2, 3], "USD"))


def test_pp():
    r = ops.pp(Q(4.10, "percent"), Q(0.0265, "ratio"))
    assert r.value == approx(1.45) and str(r.unit) == "pp"
    with pytest.raises(UnitError, match="rate"):
        ops.pp(Q(4, "USD"), Q(2, "percent"))


def test_pct_change():
    r = ops.pct_change(Q(80, "USD"), Q(100, "USD"))
    assert r.value == approx(25) and str(r.unit) == "percent"
    assert ops.pct_change(**{"from": Q(298.1, "index"), "to": Q(310.3, "index")}).value == approx(4.0925863804)
    assert ops.pct_change(Q(-50, "USD"), Q(-25, "USD")).value == approx(50)     # |from|, as calc_percentage_change
    assert ops.pct_change(Q(1, "USD mn"), Q(1_500_000, "USD")).value == approx(50)
    assert ops.pct_change(Q([1, 2], "count"), Q([2, 3], "count")).value == [approx(100), approx(50)]
    assert ops.pct_change(Q(2, "percent"), Q(3, "percent"), of_rate=True).value == approx(50)


def test_pct_change_refusals():
    with pytest.raises(QuantError, match="zero"):
        ops.pct_change(Q(0, "USD"), Q(5, "USD"))
    with pytest.raises(UnitError, match="of_rate") as e:
        ops.pct_change(Q(2, "percent"), Q(3, "percent"))
    assert e.value.code == "rate_of_rate"
    with pytest.raises(UnitError):
        ops.pct_change(Q(1, "USD"), Q(1, "EUR"))


def test_ratio():
    r = ops.ratio(Q(10, "USD"), Q(4, "USD"))
    assert r.value == approx(2.5) and str(r.unit) == "ratio"
    assert ops.ratio(Q(1, "USD mn"), Q(500_000, "USD")).value == approx(2)
    r = ops.ratio(Q(10, "USD mn"), Q(5, "count k"))
    assert r.value == approx(2000) and str(r.unit) == "USD/count"
    r = ops.ratio(Q(108, "USD"), Q(100, "EUR"))
    assert r.value == approx(1.08) and str(r.unit) == "USD/EUR"
    assert str(ops.ratio(Q(6, "USD"), Q(3)).unit) == "USD"
    with pytest.raises(QuantError, match="zero"):
        ops.ratio(Q(1, "USD"), Q(0, "USD"))


def test_bp_spread():
    r = ops.bp_spread(Q(4.10, "percent"), Q(2.65, "percent"))
    assert r.value == approx(145) and str(r.unit) == "bp"
    assert ops.bp_spread(Q(0.041, "ratio"), Q(2.65, "percent")).value == approx(145)
    assert ops.bp_spread(Q(2.65, "percent"), Q(4.10, "percent")).value == approx(-145)
    with pytest.raises(UnitError, match="must be a rate"):
        ops.bp_spread(Q(100, "USD"), Q(2, "percent"))


def test_cagr():
    r = ops.cagr(Q(100, "USD"), Q(121, "USD"), 2)
    assert r.value == approx(10) and str(r.unit) == "percent"
    assert ops.cagr(Q(100, "USD"), Q(121, "USD"), Q(730, "days")).value == approx(10)
    assert ops.cagr(Q(1, "USD mn"), Q(1_331_000, "USD"), Q(3, "years")).value == approx(10)


@pytest.mark.parametrize("args,match", [((100, 121, 0), "zero years"), ((100, 121, -1), "zero years"),
                                        ((0, 121, 2), "positive"), ((-100, 121, 2), "positive")])
def test_cagr_refusals(args, match):
    with pytest.raises(QuantError, match=match):
        ops.cagr(Q(args[0], "USD"), Q(args[1], "USD"), args[2])


def test_cagr_refuses_a_period_that_is_not_time():
    with pytest.raises(UnitError):
        ops.cagr(Q(100, "USD"), Q(121, "USD"), Q(2, "USD"))


def test_annualise():
    assert ops.annualise(Q(1, "percent"), "month", "compound").value == approx((1.01 ** 12 - 1) * 100)
    assert ops.annualise(Q(1, "percent"), "month", "simple").value == approx(12)
    assert ops.annualise(Q(2, "percent"), "quarter").value == approx((1.02 ** 4 - 1) * 100)
    assert ops.annualise(Q(1, "percent"), None, "sqrt_time", periods_per_year=252).value == approx(math.sqrt(252))
    assert ops.annualise(Q(100, "bp"), Q(0.5, "years"), "simple").value == approx(2)
    assert ops.annualise(Q(1, "percent"), Q(73, "days"), "simple").value == approx(5)
    with pytest.raises(UnitError):
        ops.annualise(Q(1, "USD"), "month")
    with pytest.raises(QuantError, match="convention"):
        ops.annualise(Q(1, "percent"), "month", "continuous")
    with pytest.raises(QuantError):
        ops.annualise(Q(1, "percent"), "fortnight")


def test_npv():
    r = ops.npv(Q([-1000, 300, 400, 500], "USD"), Q(8, "percent"))
    assert r.value == approx(17.629426408575853) and str(r.unit) == "USD"
    assert ops.npv(Q([-100, 110], "USD"), Q(10, "percent")).value == approx(0, abs_=1e-9)
    half = ops.npv(Q([-100, 50, 60], "EUR mn"), Q(0.1, "ratio"), Q(0.5, "years"))
    assert half.value == approx(-100 + 50 / 1.1 ** 0.5 + 60 / 1.1) and str(half.unit) == "EUR mn"
    with pytest.raises(UnitError):
        ops.npv(Q([-100, 110], "USD"), Q(10, "USD"))
    with pytest.raises(UnitError):
        ops.npv(Q([-1, 1], "percent"), Q(10, "percent"))
    with pytest.raises(QuantError, match="above"):
        ops.npv(Q([-100, 110], "USD"), Q(-100, "percent"))


def test_irr():
    assert ops.irr(Q([-100, 110], "USD")).value == approx(10, abs_=1e-7)
    r = ops.irr(Q([-1000, 300, 400, 500], "USD"))
    assert str(r.unit) == "percent" and ops.npv(Q([-1000, 300, 400, 500], "USD"), r).value == approx(0, abs_=1e-6)
    assert ops.irr(Q([-100, 0, 0, 133.1], "USD")).value == approx(10, abs_=1e-7)
    with pytest.raises(QuantError, match="negative and one positive"):
        ops.irr(Q([100, 200], "USD"))
    with pytest.raises(QuantError):
        ops.irr(Q([-100], "USD"))


def test_weighted_avg():
    r = ops.weighted_avg(Q([10, 20], "percent"), Q([1, 3], "USD"))
    assert r.value == approx(17.5) and str(r.unit) == "percent"
    with pytest.raises(QuantError, match="sum to zero"):
        ops.weighted_avg(Q([1, 2], "USD"), Q([1, -1]))
    with pytest.raises(QuantError, match="different lengths"):
        ops.weighted_avg(Q([1, 2], "USD"), Q([1]))


def test_aggregates():
    col = Q([2, 4, 4, 4, 5, 5, 7, 9], "USD mn")
    expect = {"sum": 40, "mean": 5, "median": 4.5, "stdev": math.sqrt(32 / 7), "min": 2, "max": 9}
    for name, want in expect.items():
        r = operation(name)(col)
        assert r.value == approx(want) and str(r.unit) == "USD mn", name
    with pytest.raises(QuantError, match="at least 2"):
        ops.q_stdev(Q([1], "USD"))
    with pytest.raises(QuantError, match="grid"):
        ops.q_sum(Q([[1, 2], [3, 4]], "USD"))


def test_regression():
    out = ops.regression(Q([3, 5, 7, 9], "USD"), Q([1, 2, 3, 4], "years"))
    assert out["slope"].value == approx(2) and out["intercept"].value == approx(1) and out["r2"].value == approx(1)
    assert str(out["slope"].unit) == "USD/years" and str(out["intercept"].unit) == "USD"
    assert str(out["r2"].unit) == "unitless"
    noisy = ops.regression(Q([1, 2, 3, 4], "USD"), Q([1, 2, 3, 5], "years"))
    assert noisy["slope"].value == approx(0.7428571428571) and noisy["r2"].value == approx(0.9657142857142)
    a, b = [1, 2, 3, 4, 5], [2, 1, 4, 3, 6]
    multi = ops.regression(Q([1 + 2 * x + 3 * y for x, y in zip(a, b)], "USD"), [Q(a, "count"), Q(b, "count")])
    assert multi["slope_1"].value == approx(2) and multi["slope_2"].value == approx(3)
    assert multi["intercept"].value == approx(1)
    assert str(ops.regression(Q([2, 4, 6], "USD"), Q([1, 2, 3], "USD"))["slope"].unit) == "ratio"
    with pytest.raises(QuantError, match="collinear"):
        ops.regression(Q([1, 2, 3], "USD"), Q([1, 1, 1]))
    with pytest.raises(QuantError, match="observations"):
        ops.regression(Q([1, 2], "USD"), Q([1, 2]))


def test_correlation():
    assert ops.correlation(Q([1, 2, 3]), Q([2, 4, 6], "USD")).value == approx(1)
    r = ops.correlation(Q([1, 2, 3]), Q([3, 2, 1]))
    assert r.value == approx(-1) and str(r.unit) == "unitless"
    with pytest.raises(QuantError, match="constant"):
        ops.correlation(Q([1, 1, 1]), Q([1, 2, 3]))


def test_convert():
    r = ops.convert(Q(45, "bp"), "percent")
    assert r.value == approx(0.45) and str(r.unit) == "percent" and r.lineage["op"] == "convert"
    with pytest.raises(UnitError):
        ops.convert(Q(1, "USD"), "EUR")
    with pytest.raises(UnitError, match="level"):
        ops.convert(Q(1, "USD"), "percent")


def test_fx_convert():
    rate = Quantity.from_tool(1.08, "USD/EUR", call_id="c9", tool="fx_rate", as_of="2026-10-10")
    r = ops.fx_convert(Q(100, "EUR mn"), rate)
    assert r.value == approx(108) and str(r.unit) == "USD mn" and r.as_of == "2026-10-10"
    back = ops.fx_convert(Q(108, "USD"), rate)
    assert back.value == approx(100) and str(back.unit) == "EUR"
    with pytest.raises(UnitError, match="quote GBP"):
        ops.fx_convert(Q(1, "GBP"), rate)
    with pytest.raises(UnitError, match="FX rate"):
        ops.fx_convert(Q(1, "EUR"), Q(1.08, "ratio"))
    with pytest.raises(UnitError):
        ops.fx_convert(Q(1, "percent"), rate)


def test_round():
    assert ops.q_round(Q(2.675, "USD"), 2).value == 2.68
    assert ops.q_round(Q(-1.5, "USD")).value == -2
    r = ops.q_round(Q([1.234, 5.678], "percent"), 1)
    assert r.value == [1.2, 5.7] and str(r.unit) == "percent"
    with pytest.raises(QuantError):
        ops.q_round(Q(1), 1.5)


def test_every_result_has_lineage_and_bare_numbers_are_constants():
    r = ops.pct_change(80, 100)
    assert r.lineage["op"] == "pct_change" and r.lineage["inputs"][0]["value"] == 80
    assert r.source == {"kind": "operation", "op": "pct_change"}


# ── the workspace ────────────────────────────────────────────────

def test_workspace_runs_operations_by_name_and_traces_lineage():
    ws = Workspace()
    ws.put("cpi_then", Quantity.from_tool(298.1, "index", call_id="c1", tool="fred_cpi", as_of="2025-09"))
    ws.put("cpi_now", Quantity.from_tool(310.3, "index", call_id="c1", tool="fred_cpi", as_of="2026-09"))
    r = ws.run("pct_change", "cpi_then", "cpi_now", name="inflation")
    assert r.value == approx(4.0925863804) and r.as_of == "2026-09" and "inflation" in ws
    ws.run("round", "inflation", 1, name="shown")
    tree = ws.lineage("shown")
    assert tree["op"] == "round" and tree["inputs"][0]["op"] == "pct_change"
    assert [i["source"]["call_id"] for i in tree["inputs"][0]["inputs"]] == ["c1", "c1"]
    out = ws.run("regression", Q([3, 5, 7], "USD"), Q([1, 2, 3]), name="fit")
    assert set(out) == {"slope", "intercept", "r2"} and "fit.slope" in ws
    auto = ws.run("sum", Q([1, 2], "USD"))
    assert auto.name == "sum_1"


def test_workspace_refusals():
    ws = Workspace({"a": Q(1, "USD")})
    with pytest.raises(QuantError, match="already"):
        ws.put("a", Q(2, "USD"))
    ws.put("a", Q(2, "USD"), replace=True)
    with pytest.raises(QuantError, match="identifier"):
        ws.put("1bad name", Q(1))
    with pytest.raises(QuantError, match="no quantity named b"):
        ws.get("b")
    with pytest.raises(UnitError):
        ws.run("diff", "a", Q(1, "EUR"), name="x")
    assert "x" not in ws


def test_workspace_json_round_trip():
    ws = Workspace()
    ws.put("spread", ops.bp_spread(Q(4.1, "percent", as_of="2026-10-10"), Q(2.65, "percent")))
    ws.put("flows", Q([[1, 2], [3, 4]], "USD mn"))
    data = json.loads(json.dumps(ws.to_json()))
    back = Workspace.from_json(data)
    assert back.names() == ["spread", "flows"] and back.get("spread").value == approx(145)
    assert str(back.get("flows").unit) == "USD mn" and back.get("spread").lineage["op"] == "bp_spread"
    assert back.to_json() == data


def test_workspace_figures_in_every_convertible_unit():
    ws = Workspace({"s": Q(45, "bp")})
    figs = {(round(v, 10), str(u)) for v, u, _ in ws.figures()}
    assert figs == {(45.0, "bp"), (0.45, "percent"), (0.45, "pp"), (0.0045, "ratio")}


def test_workspace_of_a_plan_state():
    class S:
        data = {}
    assert workspace_of(S()) is None
    ws = workspace_of(S(), create=True)
    assert workspace_of(S()) is ws and S.data["workspace"] is ws


# ── settings (§5) ────────────────────────────────────────────────

def test_quant_settings_defaults_yaml_and_env():
    s = load_settings({}, environ={})
    assert (s.max_graph_nodes, s.max_table_cells, s.day_count, s.code_act.roles) == (40, 10000, "act/365", [])
    s = load_settings({"max_graph_nodes": 10, "day_count": "act/360", "code_act": {"roles": ["quant"]}}, environ={})
    assert (s.max_graph_nodes, s.day_count, s.code_act.roles) == (10, "act/360", ["quant"])
    s = load_settings({}, environ={"SAJHA_AI_QUANT_MAX_TABLE_CELLS": "500", "SAJHA_AI_QUANT_DAY_COUNT": "30/360"})
    assert (s.max_table_cells, s.day_count) == (500, "30/360")
    assert load_settings({"day_count": "act/999"}, environ={}).day_count == "act/365"
    assert load_settings({}, environ={"SAJHA_AI_QUANT_CODE_ACT_ROLES": "admin,quant"}).code_act.roles == ["admin", "quant"]


# ── agreement with the calc folder tools ─────────────────────────

CASHFLOWS = [[-1000, 300, 400, 500], [-500, 100, 100, 100, 100, 100, 100], [-2000, 0, 0, 3000],
             [-100, 110], [-250, 60, 70, 80, 90]]


@pytest.fixture(scope="module")
def calc():
    return ToolBox()


@pytest.mark.parametrize("flows", CASHFLOWS)
@pytest.mark.parametrize("rate", [0, 5, 8, 12.5])
def test_npv_agrees_with_calc_npv(calc, flows, rate):
    tool = calc.get_tool("calc_npv").execute({"discount_rate": rate, "cash_flows": flows})
    assert round(ops.npv(Q(flows, "USD"), Q(rate, "percent")).value, 2) == tool["npv"]


@pytest.mark.parametrize("flows", CASHFLOWS)
def test_irr_agrees_with_calc_irr(calc, flows):
    tool = calc.get_tool("calc_irr").execute({"cash_flows": flows})
    mine = ops.irr(Q(flows, "USD"))
    # calc_irr bisects until |npv| < 0.01; the library solves to machine precision. Both are roots:
    assert abs(ops.npv(Q(flows, "USD"), mine).value) < 1e-6
    assert abs(ops.npv(Q(flows, "USD"), Q(tool["irr"], "percent")).value) < 0.02
    assert mine.value == pytest.approx(tool["irr"], abs=0.01)


@pytest.mark.parametrize("old,new", [(80, 100), (100, 80), (3.5, 7.25), (-50, -25), (-20, 30), (1234.5, 1234.5)])
def test_pct_change_agrees_with_calc_percentage_change(calc, old, new):
    tool = calc.get_tool("calc_percentage_change").execute({"old_value": old, "new_value": new})
    assert round(ops.pct_change(Q(old, "USD"), Q(new, "USD")).value, 4) == tool["percentage_change"]
