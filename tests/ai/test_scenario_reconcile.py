# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The scenario and reconcile planners (docs/architecture/Quantitative Planners.md §3.3, §3.8) and their
stage types (sajha/ai/planners_engine/scenario_stages.py, reconcile_stage.py), on the mock models with
fake tools: a grid bounded by max_points and the foreach limits, one call per point, a table of
quantities with lineage, a failed point reported and never filled in; readings aligned on as-of date
and unit, differences beyond the tolerance with both lineages, no comparison across currencies without
an FX rate from a tool; and dry runs that complete on mock-planner."""

import pytest

from sajha.ai.planners_engine import PlannerRegistry, get_registry, set_registry
from sajha.ai.planners_engine.settings import PlannerSettings
from sajha.ai.quant import Workspace
from tests.ai.conftest import FakeTool, ToolBox
from tests.ai.test_planner_engine import ctx, path, scripted, service

BASE_NPV = 1_000_000.0
SCENARIO_Q = "How does the book's value move if IR.FWD.SOFR.5Y is shocked from -50 bp to +50 bp in 25 bp steps?"


@pytest.fixture(autouse=True)
def registry():
    reg = PlannerRegistry()
    set_registry(reg)
    yield reg
    set_registry(None)


def pricer(fail_at=None):
    """A book pricer: total_npv falls 1,000 per bp of the shocked rate; ``fail_at`` (a size) raises."""
    def price(args):
        shocks = ((args.get("market_data") or {}).get("shocks")) or []
        bp = sum(float(s.get("size_bp") or 0) for s in shocks)
        if fail_at is not None and bp == fail_at:
            raise RuntimeError("the curve could not be rebuilt")
        return {"valuation_date": "2026-10-09", "reporting_currency": "USD", "total_npv": BASE_NPV - 1000.0 * bp}
    box = ToolBox(with_calc=False)
    tool = box.add(FakeTool("book_price_trades", "Price the trades of a book under shocks",
                            {"type": "object", "properties": {"market_data": {"type": "object"}}}, output=price))
    return box, tool


def grid_reply(sizes=(-50, -25, 25, 50), tool="book_price_trades", **over):
    g = {"tool": tool, "arguments": {"book": "B1"}, "shock_path": "market_data.shocks", "value_path": "$.total_npv",
         "unit": "USD", "as_of_path": "$.valuation_date",
         "factors": [{"factor": "IR.FWD.SOFR.5Y", "size_field": "size_bp", "shock_type": "absolute",
                      "sizes": list(sizes)}], "why": "test"}
    g.update(over)
    return {"stage": "grid", "json": g}


def workspace(r):
    return Workspace.from_json(r.workspace)


def events(svc, q, kind):
    return [e for e in svc.stream_ask(q, ctx()) if e["type"] == kind]


# ── the shipped files ────────────────────────────────────────────

@pytest.mark.parametrize("name", ["scenario", "reconcile"])
def test_the_new_planner_files_load(registry, name):
    e = registry.entry(name)
    assert e.pdef is not None and e.version == "1.0.0" and not registry.errors and not e.warnings


def test_scenario_runs_the_points_with_the_existing_foreach(registry):
    st = registry.entry("scenario").pdef.stages
    assert st["points"].type == "foreach" and st["points"].cfg["do"]["stages"]["call"]["type"] == "grid_call"
    assert [st[s].type for s in ("grid", "table")] == ["grid", "tabulate"]


# ── scenario: the grid ───────────────────────────────────────────

def test_scenario_path_one_call_per_point_and_the_table_in_the_workspace():
    box, tool = pricer()
    r = service(box, planner="scenario").ask(SCENARIO_Q, ctx())            # mock-planner defines the grid
    assert path(r) == ["grid", "points", "table", "draft", "verify", "answer"], r.caveats
    assert r.stopped_by == "answer" and len(tool.calls) == 5               # the base and four shocks
    sizes = sorted(sum(s["size_bp"] for s in (c.get("market_data") or {}).get("shocks", [])) for c in tool.calls)
    assert sizes == [-50, -25, 0, 25, 50]
    ws = workspace(r)
    assert ws.get("table.base").value == BASE_NPV and str(ws.get("table.base").unit) == "USD"
    assert ws.get("table.shocked").value == [1_050_000.0, 1_025_000.0, 975_000.0, 950_000.0]
    assert ws.get("table.change").value == [50_000.0, 25_000.0, -25_000.0, -50_000.0]
    assert ws.get("table.shock").value == [-50.0, -25.0, 25.0, 50.0] and str(ws.get("table.shock").unit) == "bp"
    assert ws.get("table.table").value[0] == [1_050_000.0, 50_000.0]
    assert not any("does not" in c for c in r.caveats)                    # the figures pass numbers_in_workspace


def test_every_difference_has_lineage_back_to_both_calls():
    box, _tool = pricer()
    gw = scripted([grid_reply(), {"stage": "draft", "json": {"answer": "The base is 1,000,000.00 USD; at +25 bp the "
                                                                      "value is 975,000.00 USD, a change of -25,000.00 "
                                                                      "(-2.50%).", "citations": [], "caveats": []}}],
                  mode="rules")
    r = service(box, gw=gw, planner="scenario").ask(SCENARIO_Q, ctx())
    ws = workspace(r)
    lin = ws.lineage("table.p3.change")
    assert lin["op"] == "diff" and [i["name"] for i in lin["inputs"]] == ["table.p3", "table.base"]
    point, base = (i["source"] for i in lin["inputs"])
    assert point["kind"] == "tool" and point["call_id"] == "point_p3" and point["path"] == "$.total_npv"
    assert point["arguments"]["market_data"]["shocks"] == [{"factor": "IR.FWD.SOFR.5Y", "shock_type": "absolute",
                                                           "size_bp": 25.0}]
    assert base["call_id"] == "point_base" and point["arguments"]["book"] == "B1"
    assert ws.get("table.p3").as_of == "2026-10-09"
    assert ws.get("table.p3.change_pct").value == pytest.approx(-2.5)
    assert ws.lineage("table.change")["inputs"][2]["name"] == "table.p3.change"
    assert path(r)[-3:] == ["draft", "verify", "answer"] and not any("does not" in c for c in r.caveats)


def test_the_model_computing_a_figure_is_caught_by_the_numbers_check():
    box, _tool = pricer()
    bad = {"stage": "draft", "json": {"answer": "A +25 bp shock costs 31,337.00 USD.", "citations": [], "caveats": []}}
    gw = scripted([grid_reply(), bad, {"stage": "revise", "json": bad["json"]}], mode="rules")
    r = service(box, gw=gw, planner="scenario").ask(SCENARIO_Q, ctx())
    assert path(r)[-4:] == ["verify", "revise", "verify", "answer"]
    assert any("31,337" in c for c in r.caveats)


def test_a_grid_beyond_max_points_goes_back_to_the_model_then_fails():
    box, tool = pricer()
    gw = scripted([grid_reply(sizes=range(-100, 101, 10)), grid_reply(sizes=range(-100, 101, 10))], mode="ordered")
    r = service(box, gw=gw, planner="scenario").ask(SCENARIO_Q, ctx())
    assert path(r) == ["grid", "fail"] and not tool.calls
    assert any("at most 9" in c for c in r.caveats)


def test_a_corrected_grid_is_accepted_after_the_errors_go_back():
    box, tool = pricer()
    gw = scripted([{"stage": "grid", "match": "does not validate: .*at most 9", "json": grid_reply()["json"]},
                   grid_reply(sizes=range(-100, 101, 10)), {"stage": "draft", "json": {"answer": "ok", "citations": [],
                                                                                       "caveats": []}}],
                  mode="rules")
    r = service(box, gw=gw, planner="scenario").ask(SCENARIO_Q, ctx())
    assert path(r)[:3] == ["grid", "points", "table"] and len(tool.calls) == 5


def test_max_points_is_a_setting_and_is_capped_by_the_foreach_limit(registry):
    box, tool = pricer()
    r = service(box, planner="scenario", planner_config={"scenario": {"max_points": 3}}).ask(SCENARIO_Q, ctx())
    assert path(r) == ["grid", "fail"] and any("at most 3" in c for c in r.caveats) and not tool.calls
    reg = get_registry()
    reg.settings = PlannerSettings(limits=reg.settings.limits.model_copy(update={"max_foreach_items": 4}))
    reg.invalidate()
    r = service(box, planner="scenario", planner_config={"scenario": {"max_points": 9}}).ask(SCENARIO_Q, ctx())
    assert path(r) == ["grid", "fail"] and any("at most 4" in c for c in r.caveats)


def test_build_grid_validates_and_expands():
    from sajha.ai.planners_engine.scenario_stages import GridError, build_grid
    g = build_grid({"tool": "t", "arguments": '{"custom_scenarios": [{"name": "s"}]}', "unit": "USD mn",
                    "shock_path": "custom_scenarios.0.shocks", "value_path": "$.scenarios[0].pnl",
                    "factors": [{"factor": "EQ.SPX", "size_field": "size_pct", "shock_type": "relative",
                                 "sizes": [-10, 0, -20]},
                                {"shock": {"risk_classes": ["IR"], "shape": "parallel"}, "label": "rates",
                                 "size_field": "size_bp", "from": -50, "to": 50, "step": 50}]},
                   offered=["t"], max_points=9)
    assert [p["id"] for p in g["points"]] == ["base", "p1", "p2", "p3", "p4"]       # 2 x 2 (zeros dropped) + base
    assert g["points"][1]["arguments"]["custom_scenarios"][0] == {
        "name": "s", "shocks": [{"factor": "EQ.SPX", "shock_type": "relative", "size_pct": -10.0},
                                {"risk_classes": ["IR"], "shape": "parallel", "size_bp": -50.0}]}
    assert g["points"][0]["arguments"] == {"custom_scenarios": [{"name": "s"}]} and g["unit"] == "USD mn"
    with pytest.raises(GridError) as e:
        build_grid({"tool": "nope", "arguments": [], "unit": "dollars", "shock_path": "a..b", "value_path": "$[?x]",
                    "factors": [{"size_field": "size_bp"}]}, offered=["t"], max_points=9)
    msg = str(e.value)
    for part in ("not offered", "arguments must be an object", "shock_path", "value_path", "unit", "give factor",
                 "give sizes"):
        assert part in msg, part


def test_a_failed_point_is_reported_not_invented():
    box, tool = pricer(fail_at=50)
    seen = []
    svc = service(box, planner="scenario")
    for e in svc.stream_ask(SCENARIO_Q, ctx(), _objects=True):
        if e["type"] == "scenario_table":
            seen.append(e)
        if e["type"] == "done":
            r = e["result"]
    assert len(tool.calls) == 5 and path(r) == ["grid", "points", "table", "draft", "verify", "answer"]
    rows = {x["label"]: x for x in seen[0]["rows"]}
    bad = rows["IR.FWD.SOFR.5Y +50 bp"]
    assert bad["status"] == "failed" and bad["value"] is None and bad["change"] is None
    assert seen[0]["failed"] == 1
    ws = workspace(r)
    assert "table.p4" not in ws and "table.p4.change" not in ws
    assert ws.get("table.shocked").value == [1_050_000.0, 1_025_000.0, 975_000.0]          # three, not four
    assert any("+50 bp failed" in c for c in r.caveats)
    assert "950,000" not in r.answer


def test_a_failed_base_leaves_no_differences():
    box, _tool = pricer(fail_at=0)
    r = service(box, planner="scenario").ask(SCENARIO_Q, ctx())
    ws = workspace(r)
    assert "table.base" not in ws and "table.change" not in ws and ws.get("table.shocked").value
    assert any("base point failed" in c for c in r.caveats)


def test_a_grid_from_the_tools_settings_asks_the_model_nothing():
    box, tool = pricer()
    fixed = dict(grid_reply(sizes=[-10, 10])["json"], factors=[{"factor": "EQ.SPX", "size_field": "size",
                                                               "sizes": [-100, 100]}])
    gw = scripted([{"stage": "draft", "json": {"answer": "described", "citations": [], "caveats": []}}], mode="rules")
    svc = service(box, gw=gw, planner="scenario", planner_config={"scenario": {"grid": fixed}})
    ev = events(svc, SCENARIO_Q, "scenario_grid")
    assert ev[0]["by"] == "settings" and ev[0]["points"] == 3
    assert [c["market_data"]["shocks"][0]["size"] for c in tool.calls if c.get("market_data")] in ([-100, 100], [100, -100])


# ── reconcile ────────────────────────────────────────────────────

def sources(a, b, c=None):
    box = ToolBox(with_calc=False)
    box.add(FakeTool("fred_gdp_fetch", "Fetch GDP from FRED", output=a))
    box.add(FakeTool("worldbank_gdp_fetch", "Fetch GDP from the World Bank", output=b))
    if c is not None:
        box.add(FakeTool("fx_rate_fetch", "Fetch the EUR USD rate", output=c))
    return box


def reconcile_script(figures, *more):
    return scripted([{"tool_calls": [{"id": "c1", "name": "fred_gdp_fetch", "arguments": {}},
                                     {"id": "c2", "name": "worldbank_gdp_fetch", "arguments": {}}]
                      + ([{"id": "c3", "name": "fx_rate_fetch", "arguments": {}}] if more and more[0] == "fx" else [])},
                     {"text": "done"}, {"json": {"figures": figures, "why": "test"}},
                     {"json": {"answer": "explained", "citations": [], "caveats": []}}], mode="ordered")


def reading(source, cid, path, unit, **kw):
    return dict({"source": source, "call_id": cid, "path": path, "unit": unit}, **kw)


def run_reconcile(box, gw, q="Does FRED's GDP agree with the World Bank's GDP?", **kw):
    svc = service(box, gw=gw, planner="reconcile", **kw)
    ev, r = [], None
    for e in svc.stream_ask(q, ctx(), _objects=True):
        if e["type"] == "reconciliation":
            ev.append(e)
        if e["type"] == "done":
            r = e["result"]
    return r, (ev[0] if ev else None)


def test_reconcile_aligns_units_and_finds_no_break_within_tolerance():
    box = sources({"gdp": 28269.2, "unit": "USD bn", "date": "2024-12-31"},
                  {"value": 28_250_000.0, "date": "2024-12-31"})
    figs = [{"name": "GDP", "readings": [reading("FRED", "c1", "$.gdp", "USD bn", as_of_path="$.date"),
                                         reading("World Bank", "c2", "$.value", "USD mn", as_of="2024-12-31")]}]
    r, ev = run_reconcile(box, reconcile_script(figs))
    assert path(r) == ["gather", "gather", "compare", "draft", "verify", "answer"]
    assert ev["figures"][0]["status"] == "compared" and ev["figures"][0]["unit"] == "USD bn" and ev["breaks"] == []
    ws = workspace(r)
    assert ws.get("compare.gdp.world_bank.aligned").value == pytest.approx(28250.0)
    assert ws.get("compare.gdp.world_bank.diff").value == pytest.approx(-19.2)
    assert ws.lineage("compare.gdp.world_bank.aligned")["op"] == "convert"


def test_a_difference_beyond_tolerance_is_listed_with_both_lineages():
    box = sources({"gdp": 100.0}, {"gdp": 101.0})
    figs = [{"name": "GDP", "readings": [reading("FRED", "c1", "$.gdp", "USD bn"),
                                         reading("WB", "c2", "$.gdp", "USD bn")]}]
    r, ev = run_reconcile(box, reconcile_script(figs))
    (b,) = ev["breaks"]
    assert b["source"] == "WB" and b["reference"] == "FRED" and b["difference"] == pytest.approx(1.0)
    assert b["difference_pct"] == pytest.approx(1.0)
    wb, fred = b["lineage"]
    assert (wb["call_id"], wb["tool"], wb["path"]) == ("c2", "worldbank_gdp_fetch", "$.gdp")
    assert (fred["call_id"], fred["tool"]) == ("c1", "fred_gdp_fetch")
    # within a wider tolerance it is not a break
    _r, ev3 = run_reconcile(sources({"gdp": 100.0}, {"gdp": 100.4}), reconcile_script(figs))
    assert ev3["breaks"] == []                                               # 0.4% < 0.5%
    _r, ev4 = run_reconcile(sources({"gdp": 100.0}, {"gdp": 101.0}), reconcile_script(figs),
                            planner_config={"reconcile": {"tolerance": 0.02}})
    assert ev4["breaks"] == []


def test_cross_currency_without_an_fx_rate_is_refused_not_converted():
    box = sources({"gdp": 100.0}, {"gdp": 92.0})
    figs = [{"name": "GDP", "readings": [reading("FRED", "c1", "$.gdp", "USD bn"),
                                         reading("ECB", "c2", "$.gdp", "EUR bn")]}]
    r, ev = run_reconcile(box, reconcile_script(figs))
    f = ev["figures"][0]
    assert f["status"] == "not_comparable" and "does not convert between currencies" in f["reason"]
    assert ev["breaks"] == [] and any("GDP was not compared" in c for c in r.caveats)
    assert "compare.gdp.ecb.diff" not in workspace(r)


def test_cross_currency_with_an_fx_rate_from_a_tool_is_compared():
    box = sources({"gdp": 100.0}, {"gdp": 92.0}, c={"rate": 1.087})
    figs = [{"name": "GDP", "readings": [reading("FRED", "c1", "$.gdp", "USD bn"),
                                         reading("ECB", "c2", "$.gdp", "EUR bn")],
             "fx": {"call_id": "c3", "path": "$.rate", "unit": "USD/EUR"}}]
    r, ev = run_reconcile(box, reconcile_script(figs, "fx"),
                          q="Does FRED's GDP agree with the World Bank's GDP at the EUR USD rate?")
    assert ev["figures"][0]["status"] == "compared"
    ws = workspace(r)
    assert ws.get("compare.gdp.ecb.fx").value == pytest.approx(100.004)
    assert ws.lineage("compare.gdp.ecb.fx")["op"] == "fx_convert" and ev["breaks"] == []
    assert ws.get("compare.gdp.fx_rate").source["call_id"] == "c3"


def test_a_level_against_a_rate_is_not_comparable():
    box = sources({"v": 100.0}, {"v": 2.5})
    figs = [{"name": "inflation", "readings": [reading("A", "c1", "$.v", "index"), reading("B", "c2", "$.v", "percent")]}]
    _r, ev = run_reconcile(box, reconcile_script(figs))
    assert ev["figures"][0]["status"] == "not_comparable" and "level" in ev["figures"][0]["reason"]


def test_series_are_aligned_on_the_as_of_period():
    a = {"observations": [{"date": "2022-01-01", "value": "100.0"}, {"date": "2023-01-01", "value": "104.0"},
                          {"date": "2024-01-01", "value": "."}]}
    b = {"data": [{"year": "2023", "v": 4.0}, {"year": "2022", "v": 3.0}, {"year": "2021", "v": 2.0}]}
    figs = [{"name": "cpi change", "align": "year",
             "readings": [reading("FRED", "c1", "$.observations", "percent", value_field="value", date_field="date"),
                          reading("WB", "c2", "$.data", "percent", value_field="v", date_field="year")]}]
    r, ev = run_reconcile(sources(a, b), reconcile_script(figs))
    ws = workspace(r)
    assert ws.get("compare.cpi_change.fred").value == [100.0, 104.0]          # 2022, 2023; 2024 "." skipped
    assert ws.get("compare.cpi_change.wb").value == [3.0, 4.0]
    assert ws.get("compare.cpi_change.table").value == [[100.0, 3.0], [104.0, 4.0]]
    assert {b["as_of"] for b in ev["breaks"]} == {"2022", "2023"}
    assert str(ws.get("compare.cpi_change.wb.diff").unit) == "pp"


def test_a_reading_that_cannot_be_read_goes_back_to_the_model():
    box = sources({"gdp": 100.0}, {"gdp": 100.0})
    bad = [{"name": "GDP", "readings": [reading("A", "c1", "$.nope", "USD"), reading("B", "c9", "$.gdp", "USD")]}]
    good = [{"name": "GDP", "readings": [reading("A", "c1", "$.gdp", "USD"), reading("B", "c2", "$.gdp", "USD")]}]
    gw = scripted([{"tool_calls": [{"id": "c1", "name": "fred_gdp_fetch", "arguments": {}},
                                   {"id": "c2", "name": "worldbank_gdp_fetch", "arguments": {}}]},
                   {"text": "done"}, {"json": {"figures": bad}}, {"json": {"figures": good}},
                   {"json": {"answer": "they agree", "citations": [], "caveats": []}}], mode="ordered")
    r, ev = run_reconcile(box, gw)
    assert ev["figures"][0]["status"] == "compared" and ev["breaks"] == []


def test_period_alignment():
    from sajha.ai.planners_engine.reconcile_stage import period
    assert period("2024-03-31", "quarter") == "2024-Q1" and period("2024-11-02T10:00", "day") == "2024-11-02"
    assert period("2024-03-31", "month") == "2024-03" and period(2024, "year") == "2024" and period(None, "day") is None


# ── dry runs on mock-planner ─────────────────────────────────────

def test_scenario_and_reconcile_dry_runs_complete_on_the_mock_planner():
    box, _tool = pricer()
    box.add(FakeTool("other_gdp_fetch", "Fetch GDP from another source", output={"gdp": 28100.0, "currency": "USD"}))
    box.add(FakeTool("fred_gdp_fetch", "Fetch GDP from FRED", output={"gdp": 28269.2, "currency": "USD"}))
    r = service(box, planner="scenario").ask(SCENARIO_Q, ctx())
    assert r.stopped_by == "answer" and r.answer
    r = service(box, planner="reconcile").ask("Fetch GDP from FRED and fetch GDP from another source", ctx())
    assert r.stopped_by == "answer" and "compare" in path(r)


def test_dry_run_endpoint_completes_for_both(monkeypatch):
    from tests.ai.test_planner_engine import PCT, _client
    c = _client(monkeypatch)
    for name in ("scenario", "reconcile"):
        body = c.post("/api/ai/planners/dry-run", json={"planner": name, "question": PCT}).json()
        assert body["planner"] == name and body["stopped_by"] in ("answer", "failed"), body
        assert body["path"][0] in ("grid", "gather")


def test_quantity_names_keep_tool_names_whole():
    # a source is usually a tool name: it was cut to 16 characters ("calc_compound_in")
    from sajha.ai.planners_engine.reconcile_stage import NAME_MAX, ident, name_budget
    from sajha.ai.quant.quantity import NAME
    fig, src = name_budget("compare", "future_value", ["calc_compound_interest", "calc_future_value"])
    used: set = set()
    names = [f"compare.{ident('future_value', used, fig)}.{ident(s, set(), src)}.fx.aligned"
             for s in ("calc_compound_interest", "calc_future_value")]
    assert names[0] == "compare.future_value.calc_compound_interest.fx.aligned"
    assert all(NAME.match(n) for n in names)
    # only a name that would pass the limit is shortened, and it still fits
    long_src = "a_really_long_tool_name_from_some_vendor_catalog_v2"
    fig, src = name_budget("compare", "consumer_price_index_change", [long_src])
    n = f"compare.{ident('consumer_price_index_change', set(), fig)}.{ident(long_src, set(), src)}.fx.aligned"
    assert len(n) <= NAME_MAX and NAME.match(n) and src >= 8
