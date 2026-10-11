# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Choosing the quantitative planners and evaluating them (docs/architecture/Quantitative Planners.md §3.9,
§4): router's quant_pattern ahead of the multi-step check, auto's new candidates (never code_act or
optimize) and eval filtering of its menu; the quantitative eval sets in config/evals/ (quant_*) run on
the mock provider, both on mock-planner and with scripted replies and recorded tool results that include
wrong graphs, wrong units, a wrong grid and an invalid formulation, to prove each is refused and re-planned
and that a figure the model computed itself never survives; and the scenario table and reconciliation
summary on the Ask result and in its audit entry."""

import pytest
import yaml

from sajha.ai.intelligence import IntelligenceService
from sajha.ai.llm import RequestContext
from sajha.ai.llm.settings import AskSettings
from sajha.ai.planners_engine import PlannerRegistry, set_registry
from sajha.quality import evals as E
from tests.ai.conftest import FakeTool, ToolBox, make_gateway
from tests.ai.test_planner_engine import ctx, path, scripted, service

try:
    import scipy  # noqa: F401
    HAVE_SCIPY = True
except ImportError:                                        # pragma: no cover - SciPy is optional
    HAVE_SCIPY = False
needs_scipy = pytest.mark.skipif(not HAVE_SCIPY, reason="SciPy is not installed: the optimize planner needs it")

SETS = E.load_sets("config/evals")
QUANT = ["quant_calc_graph", "quant_scenario", "quant_optimize"]
CAGR_Q = "What is the CAGR of revenue that grew from 120 to 180 over 5 years?"
SCENARIO_Q = "How does the book's value move if IR.FWD.SOFR.5Y is shocked from -50 bp to +50 bp in 25 bp steps?"
EVAL_CTX = dict(user_id="eval", roles=["admin"], is_admin=True)


@pytest.fixture(autouse=True)
def registry(tmp_path, monkeypatch):
    monkeypatch.setenv("SAJHA_BI_SCRATCH_DIR", str(tmp_path / "scratch"))
    reg = PlannerRegistry()
    set_registry(reg)
    yield reg
    set_registry(None)


# ── recorded tool results (the cassette): a book of 1,000,000 USD that loses 1,000 USD per bp ──

def recorded_pricer(box=None):
    """``qlrisk_price_trades`` as recorded: the book's total NPV under the shocks in market_data.shocks."""
    def price(args):
        shocks = ((args.get("market_data") or {}).get("shocks")) or []
        bp = sum(float(s.get("size_bp") or 0) for s in shocks)
        return {"valuation_date": "2026-10-09", "reporting_currency": "USD", "trade_count": 2,
                "total_npv": 1_000_000.0 - 1000.0 * bp}
    box = box or ToolBox(with_calc=False)
    box.add(FakeTool("qlrisk_price_trades", "Price the trades of a book under shocks: NPV, Greeks, cash flows",
                     {"type": "object", "properties": {"market_data": {"type": "object"}}}, output=price))
    return box


def boxes(name):
    return recorded_pricer() if name == "quant_scenario" else ToolBox()


# ── the eval sets ────────────────────────────────────────────────

def test_the_quantitative_eval_sets_ship_with_number_checks_and_tolerances():
    calc = SETS["quant_calc_graph"]
    assert {q.id for q in calc.questions} == {"pct-change", "cagr", "bp-spread", "npv", "weighted-average",
                                              "regression-slope"}
    assert SETS["quant_scenario"].planners == ["scenario"] and SETS["quant_optimize"].planners == ["optimize"]
    for name in QUANT:
        for q in SETS[name].questions:
            nums = [c for c in q.answer if "number" in c]
            assert nums and all("tolerance" in c for c in nums), (name, q.id)


@pytest.mark.parametrize("name", QUANT)
def test_each_set_passes_offline_on_mock_planner(name):
    if name == "quant_optimize" and not HAVE_SCIPY:
        pytest.skip("SciPy is not installed")
    es = SETS[name]
    svc = service(boxes(name), make_gateway(), planner_config={})
    for planner in es.planners:
        run = E.run_set(svc, es, model="mock/mock-planner", planner=planner, ctx=RequestContext(**EVAL_CTX))
        failed = [(q["id"], q["reasons"], q["answer"]) for q in run["questions"] if not q["passed"]]
        assert run["summary"]["pass_rate"] == 1.0, (planner, failed)


# ── the same sets on scripted replies: wrong graphs, wrong units, then a re-plan ──

def const(v, unit="unitless"):
    return {"value": v, "unit": unit}


def answer(text):
    return {"answer": text, "citations": [], "caveats": []}


def replan(right, wrong, draft, revise=None):
    """The first graph is ``wrong`` (refused before anything runs); the re-plan, which sees its errors, is ``right``."""
    steps = [{"stage": "graph_plan", "json": right}]
    if wrong is not None:
        steps = [{"stage": "graph_plan", "match": "^The previous computation graph", "json": right},
                 {"stage": "graph_plan", "json": wrong}]
    steps.append({"stage": "draft", "json": answer(draft)})
    if revise:
        steps.append({"stage": "revise", "json": answer(revise)})
    return steps


CPI = {"nodes": {"then": const(310.3, "index"), "now": const(319.5, "index"),
                 "move": {"op": "pct_change", "from": "then", "to": "now"}}, "answer_with": ["move"]}
CAGR = {"nodes": {"start": const(120), "end": const(180), "years": const(5, "years"),
                  "growth": {"op": "cagr", "start": "start", "end": "end", "years": "years"}}, "answer_with": ["growth"]}
SPREAD = {"nodes": {"ust": const(4.25, "percent"), "bund": const(3.80, "percent"),
                    "spread": {"op": "bp_spread", "a": "ust", "b": "bund"}}, "answer_with": ["spread"]}
NPV = {"nodes": {"flows": const([-1000, 300, 400, 500], "USD"), "rate": const(8, "percent"),
                 "value": {"op": "npv", "cash_flows": "flows", "rate": "rate"}}, "answer_with": ["value"]}
WAVG = {"nodes": {"yields": const([3.5, 4.0, 5.0], "percent"), "weights": const([50, 30, 20]),
                  "avg": {"op": "weighted_avg", "values": "yields", "weights": "weights"}}, "answer_with": ["avg"]}
SLOPE = {"nodes": {"y": const([2.1, 3.9, 6.2, 7.8, 10.1]), "x": const([1, 2, 3, 4, 5]),
                   "fit": {"op": "regression", "y": "y", "x": "x"},
                   "slope": {"op": "round", "q": "fit.slope", "places": 4}}, "answer_with": ["slope"]}

SCRIPTS = {
    # an operation that does not exist
    "pct-change": replan(CPI, {**CPI, "nodes": {**CPI["nodes"], "move": {"op": "percent_change", "from": "then",
                                                                         "to": "now"}}},
                         "The index moved 2.9649 percent."),
    # a wrong unit: the period in USD instead of years
    "cagr": replan(CAGR, {**CAGR, "nodes": {**CAGR["nodes"], "years": const(5, "USD")}},
                   "Revenue grew at a CAGR of 8.4472 percent."),
    # a wrong unit: one of the two rates declared as a currency, so there is no spread in basis points
    "bp-spread": replan(SPREAD, {**SPREAD, "nodes": {**SPREAD["nodes"], "bund": const(3.80, "USD")}},
                        "The Treasury yield is 45 bp over the Bund yield."),
    # a right graph, but the draft adds a figure the model computed itself: revised once, then it is gone
    "npv": replan(NPV, None, "The NPV is 17.6294 USD, a return of 1.8% on the outlay.",
                  revise="The NPV is 17.6294 USD."),
    # a cycle
    "weighted-average": replan(WAVG, {"nodes": {"a": {"op": "diff", "a": "b", "b": "yields"},
                                                "b": {"op": "diff", "a": "a", "b": "yields"},
                                                "yields": const([3.5, 4.0, 5.0], "percent")}, "answer_with": ["a"]},
                               "The weighted average yield is 3.95 percent."),
    "regression-slope": replan(SLOPE, None, "The regression slope is 1.99."),
}


def quantities(ws_json):
    return {q["name"]: q for q in (ws_json or {}).get("quantities") or []}


def run_scripted(es, planner, scripts, box=None):
    rows = []
    for q in es.questions:
        svc = service(box or ToolBox(), gw=scripted(scripts[q.id], mode="rules"), planner=planner, planner_config={})
        res = svc.ask(q.question, RequestContext(**EVAL_CTX))
        rows.append({**E.score(q, res), "path": path(res), "caveats": list(res.caveats), "workspace": res.workspace})
    return rows, E.summarise(rows)


def test_calc_graph_set_on_scripted_replies_refuses_wrong_graphs_and_re_plans():
    rows, summary = run_scripted(SETS["quant_calc_graph"], "calc_graph", SCRIPTS)
    by = {r["id"]: r for r in rows}
    assert summary["pass_rate"] == 1.0, [(r["id"], r["reasons"]) for r in rows if not r["passed"]]
    for qid in ("pct-change", "cagr", "bp-spread", "weighted-average"):           # refused, then re-planned
        assert by[qid]["path"][:4] == ["plan", "compute", "plan", "compute"], (qid, by[qid]["path"])
        assert by[qid]["tools_called"] == []                                       # the refusal ran nothing
    for qid in ("npv", "regression-slope"):
        assert by[qid]["path"][:3] == ["plan", "compute", "draft"]
    # the model's own 1.8% is not in the workspace: one revision removed it
    assert "revise" in by["npv"]["path"] and "1.8" not in by["npv"]["answer"]
    lineage = quantities(by["cagr"]["workspace"])["growth"]["lineage"]
    assert lineage["op"] == "cagr"


@pytest.mark.parametrize("qid,wrong,needle", [
    ("cagr", {**CAGR, "nodes": {**CAGR["nodes"], "years": const(5, "USD")}}, "cagr"),
    ("bp-spread", {**SPREAD, "nodes": {**SPREAD["nodes"], "bund": const(3.80, "USD")}}, "bp_spread"),
])
def test_a_unit_error_twice_ends_the_run_and_the_eval_fails_it(qid, wrong, needle):
    es = SETS["quant_calc_graph"]
    q = next(x for x in es.questions if x.id == qid)
    steps = [{"stage": "graph_plan", "json": wrong}, {"stage": "draft", "json": answer("45 bp, 8.4472 percent")}]
    res = service(ToolBox(), gw=scripted(steps, mode="rules"), planner="calc_graph",
                  planner_config={}).ask(q.question, RequestContext(**EVAL_CTX))
    row = E.score(q, res)
    assert path(res) == ["plan", "compute", "plan", "compute", "fail"] and res.stopped_by == "failed"
    assert not row["passed"] and any("stopped by failed" in r for r in row["reasons"])
    assert any(needle in c for c in res.caveats)                                  # the unit refusal is the reason


def test_scenario_set_on_scripted_replies_refuses_a_wrong_grid_and_tabulates_the_recorded_results():
    good = {"tool": "qlrisk_price_trades", "arguments": {"book": "B1"}, "shock_path": "market_data.shocks",
            "value_path": "$.total_npv", "unit": "USD", "as_of_path": "$.valuation_date",
            "factors": [{"factor": "IR.FWD.SOFR.5Y", "size_field": "size_bp", "shock_type": "absolute",
                         "from": -50, "to": 50, "step": 25}]}
    bad = {**good, "unit": "dollars", "value_path": "$.total_npv[?(@.x)]"}           # an unknown unit, a bad path
    script = {"sofr-ladder": [
        {"stage": "grid", "match": "^That grid does not validate", "json": good},
        {"stage": "grid", "json": bad},
        {"stage": "draft", "json": answer("The base is 1,000,000 USD. A +25 bp shock changes it by -25,000 USD; "
                                          "at -50 bp the book is worth 1,050,000 USD.")}]}
    rows, summary = run_scripted(SETS["quant_scenario"], "scenario", script, box=recorded_pricer())
    assert summary["pass_rate"] == 1.0, rows[0]["reasons"]
    assert rows[0]["tools_called"] == ["qlrisk_price_trades"] * 5                  # one call per point, base included


@needs_scipy
def test_optimize_set_on_scripted_replies_returns_an_invalid_formulation_then_solves():
    lp = {"sense": "max", "variables": [{"name": "x"}, {"name": "y"}], "objective": {"linear": {"x": 3, "y": 5}},
          "constraints": [{"terms": {"x": 1}, "op": "<=", "rhs": 4}, {"terms": {"y": 2}, "op": "<=", "rhs": 12},
                          {"terms": {"x": 3, "y": 2}, "op": "<=", "rhs": 18}]}
    bad = {**lp, "objective": {"linear": {"x": 3, "z": 5}}}                         # z is not a variable
    script = {"product-mix": [
        {"stage": "optimize", "match": "^That formulation does not validate", "json": lp},
        {"stage": "optimize", "json": bad},
        {"stage": "draft", "json": answer("The optimal objective is 36 at x = 2, y = 6.")}]}
    rows, summary = run_scripted(SETS["quant_optimize"], "optimize", script)
    assert summary["pass_rate"] == 1.0, rows[0]["reasons"]
    opt = quantities(rows[0]["workspace"])
    assert opt["solve.objective"]["value"] == pytest.approx(36)


# ── router: quant_pattern before the multi-step check (§3.9) ──────

@pytest.mark.parametrize("question,quant", [
    ("By what percent change did CPI move from 310.3 to 319.5?", True),
    (CAGR_Q, True),
    ("What is the spread in basis points between a 4.25% and a 3.80% yield?", True),
    ("What if the 5-year rate rises 50 bp?", True),
    ("Show the sensitivity of the book to SOFR", True),
    ("What is the NPV of cash flows -1000, 300, 400 at 8%?", True),
    ("What is the future value of 5000 at 7 percent for 20 years?", False),
    ("What is the price of MSFT?", False),
])
def test_the_router_pattern(question, quant):
    import re
    pattern = yaml.safe_load(open("config/planners/router.yaml"))["settings"]["quant_pattern"]
    assert bool(re.search(pattern, question, re.I)) is quant


def test_router_sends_a_computed_figure_to_calc_graph_before_the_multi_step_check(toolbox):
    svc = service(toolbox, planner="router")
    r = svc.ask(CAGR_Q, ctx())
    assert r.planner == "router>calc_graph" and "8.447" in r.answer and r.stopped_by == "answer"
    # quant comes before the multi-step check
    assert service(toolbox, planner="router").ask(
        "Compare the CAGR of revenue that grew from 120 to 180 over 5 years", ctx()).planner == "router>calc_graph"
    # recipes still come first, and other questions route as before
    assert svc.ask("What is the percentage change from 80 to 100?", ctx()).planner == "router>recipes"
    assert svc.ask("Compare the Sharpe ratio and Sortino ratio for a return of 12 with risk free rate 4 and "
                   "volatility 15", ctx()).planner == "router>plan_execute"


def test_router_quant_default_is_a_setting(toolbox):
    off = service(toolbox, planner="router", planner_config={"router": {"use_quant": False}})
    assert off.ask(CAGR_Q, ctx()).planner == "router>react"
    other = service(toolbox, planner="router", planner_config={"router": {"quant_default": "estimate_then_compute"}})
    assert other.ask(CAGR_Q, ctx()).planner.startswith("router>estimate_then_compute")


# ── auto: the new candidates, and eval filtering of its menu ─────

def test_auto_candidates():
    auto = yaml.safe_load(open("config/planners/auto.yaml"))
    cands = auto["settings"]["candidates"]
    assert {"calc_graph", "scenario", "data_analyst"} <= set(cands)
    assert "code_act" not in cands and "optimize" not in cands
    assert set(auto["settings"]["self_checked"]) <= set(cands)


def test_auto_chooses_calc_graph_for_a_computed_figure_and_does_not_escalate(toolbox):
    events = list(service(toolbox, planner="auto", planner_config={}).stream_ask(CAGR_Q, ctx()))
    r = events[-1]["result"]
    chosen = [e for e in events if e["type"] == "planner_chosen"]
    assert chosen[1]["planner"] == "calc_graph"
    assert r["planner"] == "auto>calc_graph" and [p for p in r["planner_path"] if "/" not in p] == \
        ["known", "choose", "run", "verify", "gate"]
    assert "8.447" in r["answer"] and quantities(r["workspace"])["growth"]["unit"] == "percent"


def test_auto_chooses_scenario_for_a_sensitivity_question():
    r = service(recorded_pricer(), planner="auto", planner_config={}).ask(SCENARIO_Q, ctx())
    assert r.planner == "auto>scenario" and r.stopped_by == "answer"
    assert len(r.scenario_tables) == 1 and len(r.scenario_tables[0]["rows"]) == 5


class _Runs:
    def __init__(self, runs):
        self.runs = runs

    def list(self, kind, limit=200):
        return list(self.runs)


def test_eval_filtering_drops_a_quantitative_planner_that_failed_the_tools_eval_set(registry, monkeypatch, toolbox):
    from sajha.quality import store
    es = E.parse_set({"name": "assistant_quant", "tool": "llm_quant", "questions": [{"question": CAGR_Q}]})
    monkeypatch.setattr(E, "load_sets", lambda directory=None: {es.name: es})
    store.set_run_store(_Runs([{"summary": {"set": "assistant_quant", "planner": "calc_graph", "pass_rate": 0.25}},
                               {"summary": {"set": "assistant_quant", "planner": "scenario", "pass_rate": 1.0}}]))
    try:
        cands = yaml.safe_load(open("config/planners/auto.yaml"))["settings"]["candidates"]
        kept = registry.eval_filter("llm_quant", cands)
        assert "calc_graph" not in kept and "scenario" in kept and "data_analyst" in kept
        assert registry.eval_filter("another_tool", cands) == cands                # no eval set, no filtering
        events = list(service(toolbox, planner="auto", planner_config={}).stream_ask(
            CAGR_Q, ctx(), planner_info={"tool": "llm_quant"}))
        chosen = [e["planner"] for e in events if e["type"] == "planner_chosen"]
        assert "calc_graph" not in chosen
    finally:
        store.set_run_store(None)


# ── the scenario table and the reconciliation summary on the result and in the audit ──

def audited(box, gw, planner):
    entries = []
    svc = IntelligenceService(gw, box, settings=AskSettings(audit=True, planner=planner, planner_config={}),
                              audit=entries.append)
    return svc, entries


def test_the_scenario_table_is_on_the_result_and_in_the_audit_entry():
    svc, entries = audited(recorded_pricer(), make_gateway(), "scenario")
    r = svc.ask(SCENARIO_Q, ctx())
    table = r.scenario_tables[0]
    assert table["stage"] == "table" and table["unit"] == "USD" and table["failed"] == 0
    base = next(x for x in table["rows"] if x["point"] == "base")
    assert base["value"] == 1_000_000.0 and any(x["change"] == -25_000.0 for x in table["rows"])
    assert r.to_dict()["scenario_tables"] == r.scenario_tables
    logged = [e for e in entries if e.get("scenario_tables")]
    assert logged and logged[0]["scenario_tables"][0]["rows"][0]["point"] == "base"


def test_the_reconciliation_summary_is_on_the_result_and_in_the_audit_entry():
    box = ToolBox(with_calc=False)
    box.add(FakeTool("fred_gdp_fetch", "Fetch GDP from FRED", output={"gdp": 29100.0, "date": "2025-12-31"}))
    box.add(FakeTool("worldbank_gdp_fetch", "Fetch GDP from the World Bank", output={"value": 29400.0,
                                                                                     "date": "2025-12-31"}))
    readings = [{"source": "FRED", "call_id": "c1", "path": "$.gdp", "unit": "USD bn", "as_of_path": "$.date"},
                {"source": "World Bank", "call_id": "c2", "path": "$.value", "unit": "USD bn", "as_of_path": "$.date"}]
    gw = scripted([{"tool_calls": [{"id": "c1", "name": "fred_gdp_fetch", "arguments": {}},
                                   {"id": "c2", "name": "worldbank_gdp_fetch", "arguments": {}}]},
                   {"text": "done"}, {"json": {"figures": [{"name": "GDP", "readings": readings}], "why": "test"}},
                   {"json": answer("The World Bank's GDP is 300 USD bn above FRED's.")}], mode="ordered")
    svc, entries = audited(box, gw, "reconcile")
    r = svc.ask("Does FRED's GDP agree with the World Bank's GDP?", ctx())
    rec = r.reconciliations[0]
    assert rec["stage"] == "compare" and rec["figures"][0]["status"] == "compared" and len(rec["breaks"]) == 1
    assert r.to_dict()["reconciliations"] == r.reconciliations
    logged = [e for e in entries if e.get("reconciliations")]
    assert logged and logged[0]["reconciliations"][0]["figures"][0]["name"] == rec["figures"][0]["name"]
    assert logged[0]["reconciliations"][0]["breaks"] == rec["breaks"]
