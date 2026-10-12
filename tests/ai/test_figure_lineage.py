# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Units a tool declares and a figure's lineage (docs/architecture/Quantitative Planners.md §2.1, §2.2,
Roadmap L60): the ``x-sajha-unit`` keyword of an ``outputSchema`` property, found for a read path
(``schema_unit``), ignored by JSON Schema validation and checked by lint (rule ``unit``); the workspace
recording ``unit_from: schema`` for reads in calc_graph, scenario and reconcile, the schema's unit
replacing the model's; the shipped tools' declarations; and the ``workspace`` event (the answer's
figures and their lineage) the Ask page marks."""

import glob
import json

import pytest

from sajha.ai.planners_engine import PlannerRegistry, set_registry
from sajha.ai.planners_engine.numbers import workspace_figures
from sajha.ai.quant import Quantity, Workspace, schema_unit
from sajha.ai.quant.graph import parse_graph
from sajha.ai.quant.schema_units import schema_unit_marks, unit_problem
from sajha.quality.lint import lint_tool
from tests.ai.conftest import FakeTool, ToolBox
from tests.ai.test_calc_graph import GRAPH, INFLATION, OBS, QUESTION, draft, graph, read
from tests.ai.test_planner_engine import ctx, scripted, service

FRED_SCHEMA = {"type": "object", "properties": {
    "series": {"type": "string"},
    "data": {"type": "object", "properties": {"observations": {"type": "array", "items": {
        "type": "object", "properties": {"date": {"type": "string"},
                                         "value": {"type": "string", "x-sajha-unit": "index"}}}}}}}}


@pytest.fixture(autouse=True)
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("SAJHA_BI_SCRATCH_DIR", str(tmp_path / "scratch"))
    reg = PlannerRegistry()
    set_registry(reg)
    yield reg
    set_registry(None)


def cpi_box(schema=FRED_SCHEMA):
    box = ToolBox(with_calc=False)
    tool = box.add(FakeTool("fred_cpi", "Consumer price index observations, newest first",
                            {"type": "object", "properties": {"limit": {"type": "integer"}}},
                            output={"data": {"series": "CPIAUCSL", "observations": OBS}}))
    if schema is not None:
        tool._output_schema = schema
    return box


def run(steps, box, question=QUESTION, planner="calc_graph"):
    svc = service(box, gw=scripted(steps, mode="ordered"), planner=planner)
    events = list(svc.stream_ask(question, ctx()))
    return events[-1]["result"], events


# ── the keyword ──────────────────────────────────────────────────

def test_schema_unit_follows_the_read_path():
    assert schema_unit(FRED_SCHEMA, "$.data.observations[0].value") == "index"
    assert schema_unit(FRED_SCHEMA, "$.data.observations[*].value") == "index"     # a column
    assert schema_unit(FRED_SCHEMA, "data.observations[-1].value") == "index"
    assert schema_unit(FRED_SCHEMA, "$..value") == "index"                         # recursive descent
    assert schema_unit(FRED_SCHEMA, "$.data.observations[0].date") is None        # declares nothing
    assert schema_unit(FRED_SCHEMA, "$.data.missing") is None
    assert schema_unit(FRED_SCHEMA, "$.data[?(@.x)]") is None                      # outside the subset
    assert schema_unit(None, "$.x") is None


def test_schema_unit_through_items_refs_branches_and_maps():
    s = {"type": "object", "$defs": {"rate": {"type": "number", "x-sajha-unit": "percent"}},
         "properties": {
             "rates": {"type": "array", "items": {"$ref": "#/$defs/rate"}},
             "col": {"type": "array", "items": {"type": "number"}, "x-sajha-unit": "USD mn"},
             "by_tenor": {"type": "object", "additionalProperties": {"type": ["number", "null"], "x-sajha-unit": "bp"}},
             "either": {"anyOf": [{"type": "number", "x-sajha-unit": "count"}, {"type": "null"}]},
             "mixed": {"type": "object", "properties": {"a": {"type": "number", "x-sajha-unit": "percent"},
                                                         "b": {"type": "number", "x-sajha-unit": "bp"}}},
             "bad": {"type": "number", "x-sajha-unit": "dollars"}}}
    assert schema_unit(s, "$.rates[0]") == "percent" and schema_unit(s, "$.rates") == "percent"
    assert schema_unit(s, "$.col") == "USD mn" and schema_unit(s, "$.col[2]") is None
    assert schema_unit(s, "$.by_tenor['10Y']") == "bp" and schema_unit(s, "$.by_tenor.*") == "bp"
    assert schema_unit(s, "$.either") == "count"
    assert schema_unit(s, "$.mixed.a") == "percent" and schema_unit(s, "$.mixed.*") is None   # they disagree
    assert schema_unit(s, "$.bad") is None                    # an unknown unit never reaches the workspace


def test_json_schema_validation_ignores_the_keyword():
    from jsonschema import Draft202012Validator
    from sajha.tools.base_mcp_tool import _schema_validator
    Draft202012Validator.check_schema(FRED_SCHEMA)
    v = _schema_validator(FRED_SCHEMA, "fred_cpi", None)
    v.validate({"series": "CPIAUCSL", "data": {"observations": OBS}})
    with pytest.raises(Exception):
        v.validate({"series": "CPIAUCSL", "data": {"observations": [{"value": 3.1}]}})   # the type still counts


def test_lint_checks_every_declaration():
    def findings(schema):
        return [(f.level, f.rule, f.where) for f in lint_tool("t_tool", {
            "description": "A test tool that returns numbers with units for the linter to check.",
            "inputSchema": {"type": "object", "properties": {}, "examples": [{}]}}, output_schema=schema)
            if f.rule == "unit"]
    ok = {"type": "object", "properties": {"r": {"type": "number", "x-sajha-unit": "percent"},
                                           "s": {"type": "string", "x-sajha-unit": "USD mn"},
                                           "c": {"type": "array", "items": {"type": "integer"}, "x-sajha-unit": "count k"}}}
    assert findings(ok) == []
    bad = {"type": "object", "properties": {"r": {"type": "number", "x-sajha-unit": "dollars"},
                                            "e": {"type": "number", "x-sajha-unit": ""},
                                            "n": {"type": "number", "x-sajha-unit": 3},
                                            "o": {"type": "object", "x-sajha-unit": "percent"}}}
    got = findings(bad)
    assert ("error", "unit", "properties/r") in got and ("error", "unit", "properties/e") in got
    assert ("error", "unit", "properties/n") in got and ("warning", "unit", "properties/o") in got
    assert unit_problem("USD/EUR", {"type": "number"}) == (None, None)
    # the message says once that the unit is not known (it used to say it twice)
    msgs = [f.message for f in lint_tool("t_tool", {
        "description": "A test tool that returns numbers with units for the linter to check.",
        "inputSchema": {"type": "object", "properties": {}, "examples": [{}]}}, output_schema=bad)
        if f.rule == "unit" and f.where in ("properties/r", "properties/n")]
    assert msgs and all(m.count("not one SAJHA knows") + m.count("is not a unit") <= 1 for m in msgs)
    assert all(m.count("x-sajha-unit") == 1 for m in msgs)


def test_the_shipped_declarations_are_units_and_cover_the_rate_tools():
    declared = {}
    for f in glob.glob("config/tools/**/*.json", recursive=True):
        try:
            cfg = json.load(open(f))
        except ValueError:
            continue
        for where, value, sub in schema_unit_marks(cfg.get("outputSchema")):
            error, _ = unit_problem(value, sub)
            assert error is None, (f, where, error)
            declared.setdefault(cfg.get("name"), set()).add(value)
    for name in ("fred_10yr_treasury", "fred_fed_funds_rate", "fred_unemployment", "ecb_get_interest_rate",
                 "ecb_get_bond_yield", "boc_get_interest_rate", "boj_get_policy_rate", "bis_policy_rates",
                 "ust_yield_curve", "ust_average_interest_rates", "calc_percentage_change", "calc_irr"):
        assert "percent" in declared.get(name, set()), name
    assert declared["fred_cpi"] == {"index"} and declared["fred_gdp"] == {"USD bn"}
    assert declared["fred_initial_claims"] == {"count"} and declared["fred_oil_price"] == {"USD"}
    cpi = json.load(open("config/tools/fred/fred_cpi.json"))["outputSchema"]
    assert schema_unit(cpi, "$.data.observations[0].value") == "index"


# ── the workspace reads the declaration ──────────────────────────

def test_parse_graph_takes_the_schema_unit_over_the_model_and_for_a_missing_one():
    unit_of = lambda tool, path: schema_unit(FRED_SCHEMA, path)          # noqa: E731
    g = {"nodes": {"now": read(0, unit="percent"), "then": {k: v for k, v in read(12).items() if k != "unit"},
                   "inflation": {"op": "pct_change", "from": "then", "to": "now"}}, "answer_with": ["inflation"]}
    out, errors = parse_graph(g, offered=["fred_cpi"], unit_of=unit_of)
    assert errors == [] and out.nodes["now"].spec["unit"] == "index" and out.nodes["now"].unit_from == "schema"
    assert out.nodes["then"].unit_from == "schema"
    out, errors = parse_graph(g, offered=["fred_cpi"])                   # no schema: the missing unit is an error
    assert out is None and any("declare the unit" in e for e in errors)


def test_calc_graph_records_unit_from_schema_and_the_schema_unit_wins():
    wrong = {"nodes": {**GRAPH["nodes"], "cpi_now": read(0, as_of="2026-09", unit="percent")},
             "answer_with": ["inflation"]}
    r, _ = run([graph(wrong), draft(f"Consumer prices rose {INFLATION:.2f}% over the twelve months.")], cpi_box())
    qs = {q["name"]: q for q in r["workspace"]["quantities"]}
    assert r["stopped_by"] == "answer"
    assert qs["cpi_now"]["unit"] == "index" and qs["cpi_now"]["source"]["unit_from"] == "schema"
    assert qs["inflation"]["value"] == pytest.approx(INFLATION)
    r, _ = run([graph(GRAPH), draft(f"Consumer prices rose {INFLATION:.2f}%.")], cpi_box(schema=None))
    qs = {q["name"]: q for q in r["workspace"]["quantities"]}
    assert qs["cpi_now"]["source"]["unit_from"] == "declared"


def test_scenario_and_reconcile_read_the_schema_unit():
    from tests.ai.test_quant_evals import SCENARIO_Q, recorded_pricer
    box = recorded_pricer()
    box.tools["qlrisk_price_trades"]._output_schema = {
        "type": "object", "properties": {"total_npv": {"type": "number", "x-sajha-unit": "USD"}}}
    r = service(box, planner="scenario", planner_config={}).ask(SCENARIO_Q, ctx())
    tool_reads = [q for q in r.workspace["quantities"] if (q["source"] or {}).get("kind") == "tool"]
    assert tool_reads and all(q["source"]["unit_from"] == "schema" and q["unit"] == "USD" for q in tool_reads)

    from tests.ai.test_quant_evals import answer
    box = ToolBox(with_calc=False)
    box.add(FakeTool("fred_gdp_fetch", "Fetch GDP from FRED", output={"gdp": 29100.0, "date": "2025-12-31"}))
    wb = box.add(FakeTool("worldbank_gdp_fetch", "Fetch GDP from the World Bank",
                          output={"value": 29400000.0, "date": "2025-12-31"}))
    wb._output_schema = {"type": "object", "properties": {"value": {"type": "number", "x-sajha-unit": "USD mn"}}}
    readings = [{"source": "FRED", "call_id": "c1", "path": "$.gdp", "unit": "USD bn", "as_of_path": "$.date"},
                {"source": "World Bank", "call_id": "c2", "path": "$.value", "unit": "USD bn", "as_of_path": "$.date"}]
    gw = scripted([{"tool_calls": [{"id": "c1", "name": "fred_gdp_fetch", "arguments": {}},
                                   {"id": "c2", "name": "worldbank_gdp_fetch", "arguments": {}}]},
                   {"text": "done"}, {"json": {"figures": [{"name": "GDP", "readings": readings}], "why": "test"}},
                   {"json": answer("The World Bank's GDP is 300 USD bn above FRED's.")}], mode="ordered")
    r = service(box, gw=gw, planner="reconcile").ask("Does FRED's GDP agree with the World Bank's GDP?", ctx())
    fig = r.reconciliations[0]["figures"][0]
    assert fig["status"] == "compared" and [s["unit"] for s in fig["sources"]] == ["USD bn", "USD mn"]
    qs = {q["name"]: q for q in r.workspace["quantities"]}
    wbq = next(q for n, q in qs.items() if (q["source"] or {}).get("tool") == "worldbank_gdp_fetch")
    fq = next(q for n, q in qs.items() if (q["source"] or {}).get("tool") == "fred_gdp_fetch")
    assert wbq["unit"] == "USD mn" and wbq["source"]["unit_from"] == "schema"
    assert fq["source"]["unit_from"] == "declared"
    assert len(r.reconciliations[0]["breaks"]) == 1              # 29,400 bn against 29,100 bn, after conversion


# ── the figures and their lineage (the Ask page) ─────────────────

def test_workspace_figures_mark_computed_figures_and_prefer_the_computation():
    ws = Workspace()
    ws.put("a", Quantity.of(4.25, "percent"))
    ws.put("b", Quantity.of(3.80, "percent"))
    ws.run("bp_spread", "a", "b", name="spread")
    ws.put("same", Quantity.of(45, "bp"))
    text = "The spread is 45 bp, from 4.25% and 3.80%; 1999 was a year."
    figs = workspace_figures(text, "", ws)
    spread = [f for f in figs if f["quantity"] == "spread"]
    assert spread and text[spread[0]["start"]:spread[0]["end"]] == "45 bp" and spread[0]["text"] == "45 bp"
    assert {f["quantity"] for f in figs} >= {"spread", "a", "b"}
    assert not any("1999" in f["text"] for f in figs)
    assert workspace_figures(text, "", Workspace()) == [] and workspace_figures("", "", ws) == []
    view = ws.view(["spread"])
    assert set(view) == {"spread", "a", "b"} and view["spread"]["op"] == "bp_spread"
    assert view["spread"]["inputs"] == ["a", "b"] and view["a"]["source"]["kind"] == "constant"


def test_view_clips_columns_and_keeps_inline_inputs():
    from sajha.ai.quant import ops
    ws = Workspace()
    ws.put("col", Quantity.of(list(range(1, 101)), "USD"))
    ws.run("mean", "col", name="avg")
    ws.put("lit", ops.pct_change(Quantity.of(80, "index"), Quantity.of(100, "index")))
    v = ws.view(["avg", "lit"], max_cells=5)
    assert v["col"]["value"] == [1, 2, 3, 4, 5] and v["col"]["cells"] == 100
    assert isinstance(v["lit"]["inputs"][0], dict) and v["lit"]["inputs"][0]["value"] == 80


def test_the_ask_stream_sends_the_figures_and_their_lineage_to_the_tool_call():
    r, events = run([graph(GRAPH), draft(f"Consumer prices rose {INFLATION:.2f}% over the twelve months.")],
                    cpi_box())
    kinds = [e["type"] for e in events]
    assert kinds.index("answer") < kinds.index("workspace") < kinds.index("done")
    ev = next(e for e in events if e["type"] == "workspace")
    fig = next(f for f in ev["figures"] if f["quantity"] == "inflation")
    assert fig["text"] == f"{INFLATION:.2f}%" and r["answer"][fig["start"]:fig["end"]] == fig["text"]
    q = ev["quantities"]
    assert q["inflation"]["op"] == "pct_change" and q["inflation"]["inputs"] == ["cpi_then", "cpi_now"]
    src = q["cpi_now"]["source"]
    assert src["kind"] == "tool" and src["tool"] == "fred_cpi" and src["arguments"] == {"limit": 13}
    assert src["path"] == "$.data.observations[0].value" and src["unit_from"] == "schema"
    assert src["call_id"] == r["steps"][0]["id"] and q["cpi_now"]["as_of"] == "2026-09"
    assert r["figures"] == ev["figures"]                          # the run record keeps them too


def test_an_answer_without_a_workspace_sends_no_workspace_event():
    from tests.ai.test_planner_engine import PCT
    svc = service(ToolBox(), planner="react", planner_config={})
    events = list(svc.stream_ask(PCT if isinstance(PCT, str) else "What is the percentage change from 80 to 100?",
                                 ctx()))
    assert "workspace" not in [e["type"] for e in events] and events[-1]["result"]["figures"] == []
