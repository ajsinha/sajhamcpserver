# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The calc_graph and estimate_then_compute planners (docs/architecture/Quantitative Planners.md §3.1,
§3.2), the graph_plan, compute and estimate stage types and the estimate_consistent check
(sajha/ai/planners_engine/quant_stages.py, sajha/ai/quant/graph.py), on the mock models: validation
before anything runs (cycle, unknown tool, unknown operation, bad path, unit error, node cap), one
re-plan with the errors, failed nodes failing their dependants, identical calls run once, lineage
back to the tool calls, an estimate that disagrees re-planned once then caveated; and the round-1
seams wired into the workspace: data_analyst query figures as quantities, optimize coefficients
named by quantity; dry runs of the computed-answer planners on mock-planner."""

import pytest

from sajha.ai.llm import RequestContext
from sajha.ai.planners_engine import PlannerRegistry, set_registry
from sajha.ai.quant import Quantity, Workspace
from sajha.ai.quant.graph import parse_graph
from sajha.ai.quant.settings import QuantCodeActSettings, QuantSettings, set_quant_settings
from tests.ai.conftest import FakeTool, ToolBox
from tests.ai.test_planner_engine import PCT, ctx, path, scripted, service

QUESTION = "How much did the consumer price index rise over the last 12 months, in percent?"
OBS = [{"date": f"2026-{m:02d}", "value": str(round(310.3 - 0.74 * i, 2))} for i, m in
       enumerate([9, 8, 7, 6, 5, 4, 3, 2, 1, 12, 11, 10, 9])]
NOW, THEN = float(OBS[0]["value"]), float(OBS[12]["value"])
INFLATION = (NOW - THEN) / THEN * 100


def read(i, **kw):
    return {"tool": "fred_cpi", "arguments": {"limit": 13}, "read": f"$.data.observations[{i}].value",
            "unit": "index", **kw}


GRAPH = {"nodes": {"cpi_now": read(0, as_of="2026-09"), "cpi_then": read(12),
                   "inflation": {"op": "pct_change", "from": "cpi_then", "to": "cpi_now"}},
         "answer_with": ["inflation"], "why": "the 12-month change"}


@pytest.fixture(autouse=True)
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("SAJHA_BI_SCRATCH_DIR", str(tmp_path / "scratch"))
    reg = PlannerRegistry()
    set_registry(reg)
    yield reg
    set_registry(None)
    set_quant_settings(None)


def cpi_box():
    box = ToolBox(with_calc=False)
    tool = box.add(FakeTool("fred_cpi", "Consumer price index observations, newest first",
                            {"type": "object", "properties": {"limit": {"type": "integer"}}},
                            output={"data": {"series": "CPIAUCSL", "observations": OBS}}))
    return box, tool


def graph(g):
    return {"stage": "graph_plan", "json": g}


def draft(answer):
    return {"stage": "draft", "json": {"answer": answer, "citations": [], "caveats": []}}


def ask(steps, planner="calc_graph", mode="ordered", question=QUESTION, box=None, stream=False):
    box = box or cpi_box()[0]
    svc = service(box, gw=scripted(steps, mode=mode), planner=planner)
    if stream:
        events = list(svc.stream_ask(question, ctx()))
        return events[-1]["result"], events
    return svc.ask(question, ctx())


def errors_of(g, **kw):
    kw.setdefault("offered", ["fred_cpi"])
    out, errs = parse_graph(g, **kw)
    assert out is None
    return " | ".join(errs)


# ── the shipped files ────────────────────────────────────────────

@pytest.mark.parametrize("name", ["calc_graph", "estimate_then_compute"])
def test_the_new_planner_files_load(registry, name):
    e = registry.entry(name)
    assert e.pdef is not None and e.version == "1.0.0" and not registry.errors and not e.warnings


# ── validation before anything runs ──────────────────────────────

def test_a_valid_graph_is_ordered_by_its_dependencies():
    g, errs = parse_graph(GRAPH, offered=["fred_cpi"])
    assert not errs and g.order.index("inflation") > max(g.order.index("cpi_now"), g.order.index("cpi_then"))
    assert [n.name for n in g.tool_nodes()] == ["cpi_now", "cpi_then"] and g.answer_with == ["inflation"]


def test_a_cycle_is_refused():
    g = {"nodes": {"a": {"op": "diff", "a": "b", "b": "c"}, "b": {"op": "diff", "a": "a", "b": "c"},
                   "c": {"value": 1, "unit": "USD"}}, "answer_with": ["a"]}
    assert "cycle: a -> b -> a" in errors_of(g)


def test_a_tool_not_offered_is_refused():
    assert "the tool fred_cpi is not offered" in errors_of(GRAPH, offered=["other_tool"])


def test_an_unknown_operation_is_refused():
    g = {"nodes": {**GRAPH["nodes"], "inflation": {"op": "percent_change", "from": "cpi_then", "to": "cpi_now"}},
         "answer_with": ["inflation"]}
    assert "no operation 'percent_change'" in errors_of(g)


def test_a_read_path_that_does_not_parse_is_refused():
    g = {"nodes": {**GRAPH["nodes"], "cpi_now": read(0, read="$.data.observations[?(@.x)]")},
         "answer_with": ["inflation"]}
    assert "node cpi_now: the read path" in errors_of(g)


def test_a_unit_error_on_the_declared_units_is_refused_before_any_call():
    g = {"nodes": {"usd": {"value": 100, "unit": "USD"}, "eur": read(0, unit="EUR"),
                   "total": {"op": "diff", "a": "usd", "b": "eur"}}, "answer_with": ["total"]}
    assert "node total: diff: EUR and USD cannot be combined" in errors_of(g)
    rate = {"nodes": {"a": {"value": 4.1, "unit": "percent"}, "b": {"value": 2.65, "unit": "percent"},
                      "chg": {"op": "pct_change", "from": "b", "to": "a"}}, "answer_with": ["chg"]}
    assert "percent change of a rate" in errors_of(rate)


def test_the_node_cap_is_ai_quant_max_graph_nodes():
    nodes = {f"n{i}": {"value": i, "unit": "count"} for i in range(5)}
    assert "at most 4 are allowed" in errors_of({"nodes": nodes, "answer_with": ["n0"]}, max_nodes=4)
    set_quant_settings(QuantSettings(max_graph_nodes=2))
    big = {"nodes": {**GRAPH["nodes"], "extra": {"value": 1, "unit": "index"}}, "answer_with": ["inflation"]}
    r = ask([graph(big), graph(big)])
    assert path(r) == ["plan", "compute", "plan", "compute", "fail"] and r.stopped_by == "failed"
    assert any("ai.quant.max_graph_nodes" in c for c in r.caveats) and not r.steps     # nothing ran


def test_other_refusals_name_the_node():
    g = {"nodes": {"x": {"tool": "fred_cpi", "read": "$.v"}, "y": {"value": 1, "op": "sum"},
                   "bad name": {"value": 1}, "z": {"op": "sum", "column": "x", "colour": 1}},
         "answer_with": ["nope"]}
    text = errors_of(g)
    for part in ("node x: declare the unit", "node y: give exactly one", "node bad name:",
                 "answer_with: 'nope' is not a node"):
        assert part in text
    ws_taken = errors_of(GRAPH, taken=["inflation"])
    assert "already has a quantity named inflation" in ws_taken


# ── execution ────────────────────────────────────────────────────

def test_calc_graph_runs_identical_calls_once_and_keeps_lineage_to_the_call():
    box, tool = cpi_box()
    r, events = ask([graph(GRAPH), draft(f"Consumer prices rose {INFLATION:.2f}% over the twelve months.")],
                    box=box, stream=True)
    assert [p for p in r["planner_path"] if "/" not in p] == ["plan", "compute", "draft", "verify", "answer"]
    assert r["stopped_by"] == "answer" and len(tool.calls) == 1 and len(r["steps"]) == 1     # one call, two reads
    call_id = r["steps"][0]["id"]
    qs = {q["name"]: q for q in r["workspace"]["quantities"]}
    assert qs["inflation"]["value"] == pytest.approx(INFLATION) and qs["inflation"]["unit"] == "percent"
    assert qs["cpi_now"]["source"]["call_id"] == call_id and qs["cpi_now"]["as_of"] == "2026-09"
    assert qs["cpi_then"]["source"]["path"] == "$.data.observations[12].value"
    assert qs["inflation"]["lineage"]["inputs"] == ["cpi_then", "cpi_now"]
    assert not r["caveats"]                                        # the figure matched the workspace
    assert [(e["status"], e["attempt"]) for e in events if e["type"] == "graph"] == [("done", 1)]


def test_a_figure_not_computed_is_caught_by_numbers_in_workspace():
    r = ask([graph(GRAPH), draft("Consumer prices rose 7.4% over the year."), draft("Prices rose 7.4%.")])
    assert path(r)[-4:] == ["verify", "revise", "verify", "answer"]
    assert any("7.4" in c and "computed quantity" in c for c in r.caveats)


def test_an_invalid_graph_is_re_planned_once_with_the_errors():
    bad = {"nodes": {**GRAPH["nodes"], "inflation": {"op": "growth", "from": "cpi_then", "to": "cpi_now"}},
           "answer_with": ["inflation"]}
    steps = [{"stage": "graph_plan", "match": "no operation 'growth'", "json": GRAPH}, graph(bad),
             draft(f"Prices rose {INFLATION:.2f}%.")]
    r = ask(steps, mode="rules")
    assert path(r) == ["plan", "compute", "plan", "compute", "draft", "verify", "answer"]
    assert r.stopped_by == "answer" and len(r.steps) == 1


def test_a_failed_node_fails_its_dependants_and_the_re_plan_is_told_which():
    box, tool = cpi_box()
    broken = {"nodes": {**GRAPH["nodes"], "cpi_then": read(12, read="$.data.observations[12].level")},
              "answer_with": ["inflation"]}
    steps = [{"stage": "graph_plan", "match": "inflation: needs cpi_then, which failed", "json": GRAPH},
             graph(broken), draft(f"Prices rose {INFLATION:.2f}%.")]
    r, events = ask(steps, mode="rules", box=box, stream=True)
    graphs = [e for e in events if e["type"] == "graph"]
    assert [g["status"] for g in graphs] == ["failed", "done"]
    assert "matches nothing" in graphs[0]["failed"]["cpi_then"]
    assert graphs[0]["failed"]["inflation"] == "needs cpi_then, which failed"
    assert len(tool.calls) == 1               # the re-plan reused the identical call's result
    names = [q["name"] for q in r["workspace"]["quantities"]]
    assert sorted(names) == ["cpi_now", "cpi_then", "inflation"]  # the failed graph's quantities were replaced


def test_a_graph_that_fails_twice_ends_failed():
    broken = {"nodes": {**GRAPH["nodes"], "cpi_now": read(0, read="$.nothing")}, "answer_with": ["inflation"]}
    r = ask([graph(broken), graph(broken)])
    assert path(r) == ["plan", "compute", "plan", "compute", "fail"] and r.stopped_by == "failed"
    assert any("could not be computed" in c for c in r.caveats)


def test_a_failed_tool_call_fails_its_reads():
    box = ToolBox(with_calc=False)
    box.add(FakeTool("fred_cpi", "Consumer price index observations", output={"error": "upstream down"}))
    r = ask([graph(GRAPH), graph(GRAPH)], box=box)
    assert r.stopped_by == "failed" and any("fred_cpi call failed" in c for c in r.caveats)


# ── estimate_then_compute ────────────────────────────────────────

def estimate(value, unit="percent"):
    return {"stage": "estimate", "json": {"value": value, "unit": unit, "why": "rough"}}


def test_an_estimate_that_agrees_passes_without_a_caveat():
    r = ask([estimate(3), graph(GRAPH), draft(f"Prices rose {INFLATION:.2f}%.")], planner="estimate_then_compute")
    assert path(r) == ["estimate", "compute", "check", "final", "answer"]
    assert r.planner == "estimate_then_compute>calc_graph" or r.planner.startswith("estimate_then_compute")
    assert not r.caveats and f"{INFLATION:.2f}" in r.answer


def test_an_estimate_that_disagrees_re_plans_once_naming_both_then_caveats():
    steps = [estimate(300), {"stage": "graph_plan", "match": "disagrees with a rough estimate", "json": GRAPH},
             graph(GRAPH), draft(f"Prices rose {INFLATION:.2f}%.")]
    r = ask(steps, planner="estimate_then_compute", mode="rules")
    assert path(r) == ["estimate", "compute", "check", "recompute", "check", "final", "answer"]
    assert f"{INFLATION:.2f}" in r.answer and "300" not in r.answer           # the computed figure wins
    cav = [c for c in r.caveats if "rough estimate" in c]
    assert len(cav) == 1 and "300 percent" in cav[0] and "factor of 10" in cav[0]


def test_a_re_plan_that_fixes_the_scale_clears_the_mismatch():
    as_ratio = {"nodes": {**GRAPH["nodes"], "inflation": {"op": "ratio", "a": "cpi_now", "b": "cpi_then"}},
                "answer_with": ["inflation"]}
    steps = [estimate(3), {"stage": "graph_plan", "match": "disagrees with a rough estimate", "json": GRAPH},
             graph(as_ratio), draft("The answer is as computed.")]
    r = ask(steps, planner="estimate_then_compute", mode="rules")
    assert path(r) == ["estimate", "compute", "check", "recompute", "check", "final", "answer"]
    assert not any("rough estimate" in c for c in r.caveats)
    assert {q["name"]: q for q in r.workspace["quantities"]}["inflation"]["unit"] == "percent"


def test_estimate_consistent_reports_a_unit_disagreement_and_the_factor():
    from sajha.ai.planners_engine.checks import CheckContext, checks
    ws = Workspace()
    ws.put("x", Quantity.of(2.95, "percent"))
    slots = {"estimate": {"value": 3, "unit": "USD"}, "graph": {"answer_with": ["x"]}}
    c = CheckContext(draft="", draft_json=None, citations=[], question="", results=[], output_schema=None,
                     lookup=slots.get, evaluate=lambda e: True, workspace=ws)
    check = checks()["estimate_consistent"]
    assert "units do not agree" in check(c, {})[0]["message"]
    slots["estimate"] = {"value": 0.03, "unit": "ratio"}             # 3 percent: converted, agrees
    assert check(c, {}) == []
    slots["estimate"] = {"value": 0.25, "unit": "percent"}
    assert check(c, {}) and check(c, {"tolerance_factor": 20}) == []
    slots["estimate"] = None
    assert check(c, {}) == []                                        # no estimate: nothing to compare


# ── the round-1 seams ────────────────────────────────────────────

def test_data_analyst_query_figures_enter_the_workspace_with_lineage():
    from sajha.ai.planners_engine.checks import CheckContext, checks
    from tests.ai.test_data_planners import QUESTION as SALES, draft as sales_draft, gather_then, sales_box, sql
    box, _tool, rows = sales_box()
    total = sum(x["sales"] for x in rows)
    gw = gather_then(sql("SELECT count(*) AS n, sum(sales) AS total, max(region) AS top FROM sales_rows_fetch"),
                     sales_draft(f"Total sales were {total:,} [query_1]."))
    r = service(box, gw=gw, planner="data_analyst").ask(SALES, ctx())
    qs = {q["name"]: q for q in r.workspace["quantities"]}
    assert set(qs) == {"query_1.n", "query_1.total"}                 # the text column is left out
    assert qs["query_1.total"]["value"] == total and r.queries[0]["quantities"] == ["query_1.n", "query_1.total"]
    lin = qs["query_1.total"]["lineage"]
    assert lin["op"] == "sql" and lin["args"]["query"] == "query_1"
    assert lin["inputs"] == [{"call_id": r.steps[0].id, "tool": "sales_rows_fetch"}]
    ws = Workspace.from_json(r.workspace)
    c = CheckContext(draft=f"Total sales were {total:,}.", draft_json=None, citations=[], question="", results=[],
                     output_schema=None, lookup=lambda ref: None, evaluate=lambda e: True, workspace=ws)
    assert checks()["numbers_in_workspace"](c, {}) == []            # matched through the workspace alone


def test_optimize_resolves_workspace_quantity_names_as_coefficients():
    from sajha.ai.optimize.formulation import parse_formulation
    from sajha.ai.optimize.stage import _resolver, _schema
    import jsonschema
    qs = {"cap": Quantity.of(4, "count"), "margin": Quantity.of(3, "USD")}
    used = []
    form = {"sense": "max", "variables": [{"name": "x"}], "objective": {"linear": {"x": "margin"}},
            "constraints": [{"name": "c", "terms": {"x": 1}, "op": "<=", "rhs": "cap"}]}
    jsonschema.validate(form, _schema())
    p = parse_formulation(form, resolve=_resolver(qs, used))
    assert p.linear == {"x": 3.0} and p.constraints[0].rhs == 4.0 and used == ["margin", "cap"]
    with pytest.raises(Exception, match="'nope' is not a quantity in the workspace"):
        parse_formulation({**form, "objective": {"linear": {"x": "nope"}}}, resolve=_resolver(qs, []))


def test_optimize_after_a_graph_uses_its_quantities_end_to_end():
    pytest.importorskip("scipy.optimize")
    inline = {"description": "graph then solve", "use_when": "tests", "start": "plan", "stages": {
        "plan": {"type": "graph_plan", "outcomes": {"planned": {"next": "compute"}, "invalid": {"next": "fail"}}},
        "compute": {"type": "compute", "outcomes": {"done": {"next": "solve"}, "invalid": {"next": "fail"},
                                                    "failed": {"next": "fail"}}},
        "solve": {"type": "optimize", "outcomes": {o: {"next": "draft"} for o in
                                                   ("solved", "infeasible", "unbounded", "failed")} | {
            "invalid": {"next": "fail"}}},
        "draft": {"type": "draft", "next": "answer"}, "answer": {"type": "answer"}, "fail": {"type": "fail", "reason": "no"}}}
    g = {"nodes": {"cap": {"value": 4, "unit": "count"}, "margin": {"value": 3, "unit": "USD"}},
         "answer_with": ["cap"]}
    form = {"sense": "max", "variables": [{"name": "x"}], "objective": {"linear": {"x": "margin"}},
            "constraints": [{"name": "c", "terms": {"x": 1}, "op": "<=", "rhs": "cap"}]}
    gw = scripted([graph(g), {"stage": "optimize", "json": form}, draft("Make 4 for 12 USD.")], mode="ordered")
    r = service(ToolBox(with_calc=False), gw=gw).ask("Best output?", ctx(), planner=inline,
                                                    planner_info={"inline_defaults": {"name": "x", "version": "1.0.0"}})
    assert r.stopped_by == "answer"
    qs = {q["name"]: q for q in r.workspace["quantities"]}
    assert qs["solve.objective"]["value"] == pytest.approx(12) and qs["solve.x"]["value"] == pytest.approx(4)
    assert qs["solve.objective"]["lineage"]["inputs"] == ["margin", "cap"]


# ── dry runs on mock-planner ─────────────────────────────────────

ADMIN = RequestContext(user_id="admin", roles=["admin"], is_admin=True)


@pytest.mark.parametrize("name, expected", [
    ("calc_graph", ["plan", "compute", "draft", "verify", "answer"]),
    ("estimate_then_compute", ["estimate", "compute", "check", "final", "answer"]),
])
def test_dry_runs_of_the_graph_planners_complete(name, expected):
    from sajha.ai.planners_engine.dryrun import dry_run
    out = dry_run(service(), name, PCT, ADMIN)
    assert out["path"] == expected and out["stopped_by"] == "answer" and "25" in out["answer"]


def test_dry_run_of_optimize_completes():
    pytest.importorskip("scipy.optimize")
    from sajha.ai.planners_engine.dryrun import dry_run
    out = dry_run(service(), "optimize", "What is the most we can make with at most 7 units?", ADMIN)
    assert out["path"][0] == "gather" and out["path"][-3:] == ["solve", "draft", "answer"]
    assert out["stopped_by"] == "answer"


def test_dry_run_of_code_act_completes():
    from sajha.ai.planners_engine.dryrun import dry_run
    set_quant_settings(QuantSettings(code_act=QuantCodeActSettings(roles=["admin"])))
    out = dry_run(service(), "code_act", "Add 6 and 7.", ADMIN)
    assert out["path"] == ["gather", "compute", "draft", "answer"] and out["stopped_by"] == "answer"
