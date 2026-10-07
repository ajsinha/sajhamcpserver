"""The configurable planner engine (sajha/ai/planners_engine; docs/architecture/Planner Reference.md):
the shipped files (schema, plain yaml.safe_load), a path test per shipped strategy against the
mock model, bound tests (a critic that never passes exhausts and still answers), the validation
rules P001–P071, YAML safety (P006), the expression language, resolution for LLM tools and Ask
SAJHA, automatic selection and escalation, ask_user (needs_input and MRTR), sub-budgets, the new
stopped_by values, reload with last-good fallback, custom stage types, events, metrics, audit and
the dry-run endpoint."""

import copy
import glob
import json
import os

import pytest
import yaml

from sajha.ai.intelligence import IntelligenceService
from sajha.ai.llm import RequestContext
from sajha.ai.llm.settings import AskSettings
from sajha.ai.planners_engine import (PlannerError, PlannerRegistry, compile_planner, get_registry, planner_schema,
                                      register_stage_type, set_registry, unregister_stage_type)
from sajha.ai.planners_engine import expr as E
from sajha.ai.planners_engine.settings import PlannerSettings
from tests.ai.conftest import FakeTool, ToolBox, make_gateway

PCT = "What is the percentage change from 80 to 100?"
MULTI = "Compare the Sharpe ratio and Sortino ratio for a return of 12 with risk free rate 4 and volatility 15"
RECIPES = {"recipes": {"recipes": [{"name": "pct", "tool": "calc_percentage_change",
                                    "match": r"percentage change from (?P<old_value>[\d.,]+) to (?P<new_value>[\d.,]+)",
                                    "answer": "From {old_value} to {new_value} is a change of {percentage_change}%."}]}}
SHIPPED = sorted(os.path.basename(p)[:-5] for p in glob.glob("config/planners/*.yaml"))


@pytest.fixture(autouse=True)
def registry():
    reg = PlannerRegistry()
    set_registry(reg)
    yield reg
    set_registry(None)


def ctx(**kw):
    return RequestContext(user_id="u", **kw)


def service(toolbox=None, gw=None, planner="react", planner_config=None, **ask):
    settings = AskSettings(**{"audit": False, "planner": planner,
                              "planner_config": RECIPES if planner_config is None else planner_config, **ask})
    return IntelligenceService(gw or make_gateway(), toolbox or ToolBox(), settings=settings)


def scripted(steps, mode="rules"):
    gw = make_gateway({"aliases": {a: ["mock/mock-scripted"] for a in ("default", "fast", "reasoning")},
                       "cache": {"enabled": False}})
    gw.providers["mock"].set_script(steps, mode=mode)
    return gw


def path(r):
    return [p for p in r.planner_path if "/" not in p]


def doc(**over):
    base = {"name": "t", "version": "1.0.0", "description": "A test planner.", "use_when": "Tests.",
            "start": "act", "stages": {"act": {"type": "act", "outcomes": {"called": {"next": "act", "max_visits": "steps"},
                                                                            "answered": {"next": "answer"}}},
                                       "answer": {"type": "answer"}}}
    base.update(over)
    return base


def codes(d, **kw):
    try:
        p = compile_planner(d, **kw)
    except PlannerError as e:
        return set(e.codes)
    return {w.code for w in p.warnings} | {"OK"}


# ── the shipped files ────────────────────────────────────────────

def test_every_strategy_ships():
    assert set(SHIPPED) == {"react", "plan_execute", "rewoo", "reflect", "verify_then_answer", "self_consistency",
                            "branch_and_judge", "map_reduce", "router", "recipes", "human_in_the_loop", "auto"}


@pytest.mark.parametrize("name", SHIPPED)
def test_shipped_files_load_with_plain_safe_load_and_match_the_schema(name, registry):
    import jsonschema
    with open(f"config/planners/{name}.yaml") as f:
        d = yaml.safe_load(f)
    assert all(isinstance(k, str) for k in d) and d["name"] == name
    jsonschema.Draft202012Validator(planner_schema()).validate(d)
    assert registry.entry(name).pdef is not None and not registry.errors


def test_the_schema_is_the_one_in_the_reference():
    text = open("docs/architecture/Planner Reference.md").read()
    block = text[text.index("## Appendix A"):]
    block = block[block.index("```json") + 7:]
    assert json.loads(block[:block.index("```")]) == planner_schema()


# ── path tests: one per shipped strategy, against the mock model ──

@pytest.mark.parametrize("name,question,expected,chain", [
    ("react", PCT, ["act", "act", "answer"], "react"),
    ("plan_execute", PCT, ["plan", "execute", "answer"], "plan_execute"),
    ("rewoo", PCT, ["plan", "execute", "solve", "answer"], "rewoo"),
    ("reflect", PCT, ["act", "act", "draft", "critique", "answer"], "reflect"),
    ("verify_then_answer", PCT, ["act", "act", "draft", "verify", "answer"], "verify_then_answer"),
    ("self_consistency", PCT, ["act", "act", "drafts", "pick", "answer"], "self_consistency"),
    ("branch_and_judge", PCT, ["branch", "judge", "execute", "draft", "answer"], "branch_and_judge"),
    ("map_reduce", PCT, ["gather", "gather", "list", "direct", "answer"], "map_reduce"),
    ("router", PCT, ["rules", "recipes_check", "to_recipes", "answer"], "router>recipes"),
    ("router", MULTI, ["rules", "recipes_check", "shape", "multi", "answer"], "router>plan_execute"),
    ("recipes", PCT, ["match", "call", "finish"], "recipes"),
    ("human_in_the_loop", PCT, ["clarity", "plan", "run_small", "draft", "answer"], "human_in_the_loop"),
    ("auto", PCT, ["known", "recipe", "answer"], "auto>recipes"),
    ("auto", MULTI, ["known", "choose", "run", "verify", "gate"], "auto>plan_execute"),
])
def test_path_of_each_shipped_strategy(name, question, expected, chain):
    r = service(planner=name).ask(question, ctx())
    assert path(r) == expected and r.planner == chain and r.stopped_by == "answer"
    assert r.steps and r.steps[0].ok and r.answer and r.planner_version == "1.0.0"


def test_map_reduce_answers_per_item():
    box = ToolBox(with_calc=False)
    quote = box.add(FakeTool("stock_quote_fetch", "Fetch the stock quote price for a symbol",
                             {"type": "object", "properties": {"symbol": {"type": "string"}}},
                             output=lambda a: {"symbol": a.get("symbol"), "price": 100}))
    r = service(box, planner="map_reduce").ask("Fetch the stock quote for MSFT and AAPL", ctx())
    assert path(r)[-3:] == ["list", "each", "reduce"] or path(r)[-3:] == ["each", "reduce", "answer"]
    assert {c["symbol"] for c in quote.calls} >= {"MSFT", "AAPL"}
    assert "MSFT" in r.answer and "AAPL" in r.answer and r.stopped_by == "answer"


def test_stage_events_show_the_path_on_the_ask_stream():
    events = list(service(planner="reflect").stream_ask(PCT, ctx()))
    starts = [e for e in events if e["type"] == "stage_start"]
    ends = [e for e in events if e["type"] == "stage_end"]
    assert [e["stage"] for e in starts] == ["act", "act", "draft", "critique", "answer"]
    assert all({"stage", "stage_type", "visit", "planner"} <= set(e) for e in starts)
    assert all({"stage", "outcome", "ms", "planner"} <= set(e) for e in ends)
    chosen = [e for e in events if e["type"] == "planner_chosen"]
    assert chosen[0]["planner"] == "reflect" and chosen[0]["by"] == "server default"


# ── bounds ───────────────────────────────────────────────────────

CALL = {"stage": "act", "tool_calls": [{"name": "calc_percentage_change", "arguments": {"old_value": 80, "new_value": 100}}]}


def test_a_critic_that_never_passes_exhausts_and_still_answers():
    gw = scripted([
        {"stage": "act", "match": "^What is", "text": "It is 25 percent."},
        {"stage": "draft", "json": {"answer": "The change is 25.0%.", "citations": [], "caveats": []}},
        {"stage": "critique", "json": {"verdict": "revise", "issues": [{"criterion": "c", "problem": "p",
                                                                        "suggestion": "s"}]}},
        {"stage": "revise", "json": {"answer": "The change is 25.0% (revised).", "citations": [], "caveats": []}},
    ])
    events = list(service(gw=gw, planner="reflect").stream_ask(PCT, ctx()))
    r = events[-1]["result"]
    assert r["stopped_by"] == "answer" and "revised" in r["answer"]
    assert path_of(r) == ["act", "draft", "critique", "revise", "critique", "revise", "critique", "answer"]
    assert r["loops_exhausted"] == ["reflect:critique:revise[0]"]
    ex = [e for e in events if e["type"] == "loop_exhausted"]
    assert ex and ex[0]["to"] == "answer"
    from sajha.observability.metrics import REGISTRY
    assert REGISTRY.family("sajha_planner_loops_exhausted_total").value(("reflect", "critique:revise[0]")) >= 1


def path_of(r):
    return [p for p in r["planner_path"] if "/" not in p]


def test_verify_mismatch_revises_then_answers_with_caveats():
    still = {"json": {"answer": "Still 31.7%.", "citations": [], "caveats": []}}
    gw = scripted([CALL, {"text": "done"}, {"json": {"answer": "The change is 31.7%.", "citations": [], "caveats": []}},
                   still, still], mode="ordered")
    r = service(gw=gw, planner="verify_then_answer", synthesize=False).ask(PCT, ctx())
    assert path(r) == ["act", "act", "draft", "verify", "revise", "verify", "revise", "verify", "answer"]
    assert any("31.7" in c for c in r.caveats) and r.stopped_by == "answer"


def test_react_ends_at_the_step_limit_as_today():
    gw = scripted([CALL])
    r = service(gw=gw, planner="react", max_steps=3).ask(PCT, ctx())
    assert r.stopped_by == "step_limit" and len(r.steps) == 3


def test_stage_limit_ends_the_run():
    reg = get_registry()
    reg.settings = PlannerSettings(limits=reg.settings.limits.model_copy(update={"max_stages_run": 3}))
    reg.invalidate()
    r = service(planner="reflect").ask(PCT, ctx())
    assert r.stopped_by == "stage_limit" and len(r.planner_path) == 3 and r.answer


def test_a_fail_stage_ends_failed_and_is_an_error_for_llm_tools():
    d = doc(start="check", stages={"check": {"type": "fail", "reason": "No data for {{question}}"}})
    r = service().ask(PCT, ctx(), planner=d, planner_info={"inline_defaults": {"name": "x", "version": "1.0.0"}})
    assert r.stopped_by == "failed" and r.answer == f"No data for {PCT}"
    from sajha.ai.llm_tools.tool import ERROR_STOPS
    assert "failed" in ERROR_STOPS


def test_no_transition_is_an_error():
    d = doc(start="act", stages={"act": {"type": "act", "outcomes": {
        "called": [{"next": "answer", "when": "false"}], "answered": {"next": "answer"}}}, "answer": {"type": "answer"}})
    r = service().ask(PCT, ctx(), planner=d, planner_info={"inline_defaults": {"name": "x", "version": "1.0.0"}})
    assert r.stopped_by == "error" and "no transition" in r.error


def test_sub_budget_stops_only_the_sub_run():
    d = doc(start="first", stages={
        "first": {"type": "planner", "planner": "react", "limits": {"max_steps": 1},
                  "outcomes": {"stopped": {"next": "again"}, "*": {"next": "answer"}}},
        "again": {"type": "planner", "planner": "react", "next": "answer"},
        "answer": {"type": "answer"}})
    gw = scripted([CALL | {"match": "^What is"}], mode="rules")
    r = service(gw=gw).ask(PCT, ctx(), planner=d, planner_info={"inline_defaults": {"name": "x", "version": "1.0.0"}})
    assert path(r)[:2] == ["first", "again"] and r.stopped_by == "step_limit"


# ── automatic selection and escalation (§13.12) ──────────────────

def test_auto_chooses_from_the_allowed_menu_by_label():
    events = list(service(planner="auto").stream_ask(MULTI, ctx()))
    chosen = [e for e in events if e["type"] == "planner_chosen"]
    assert [c["planner"] for c in chosen][:2] == ["auto", "plan_execute"]
    assert chosen[1]["by"].startswith("label 0.8")


def test_auto_escalates_once_when_parts_are_unanswered():
    gw = scripted([{"json": {"label": "react", "confidence": 0.9, "reason": "simple"}}, CALL,
                   {"text": "Only the first part: 25.0."}, {"json": {"steps": []}}, {"text": "Both parts."}],
                  mode="ordered")
    q = "What is the percentage change from 80 to 100? What is the future value of 5000 at 7 percent for 20 years?"
    r = service(gw=gw, planner="auto", planner_config={}).ask(q, ctx())
    p = path(r)
    assert p[:4] == ["known", "choose", "run", "verify"] and "split" in p and r.stopped_by == "answer"
    assert r.loops_exhausted == [] and p.count("split") == 1


def test_auto_escalates_when_the_first_try_runs_out_of_its_step_budget():
    gw = scripted([
        {"stage": "classify", "json": {"label": "react", "confidence": 0.9, "reason": "simple"}},
        CALL | {"stage": "act"},
        {"stage": "plan", "json": {"steps": []}},
    ])
    r = service(gw=gw, planner="auto", planner_config={}, max_steps=8).ask(PCT + " x", ctx())
    assert "gate" in path(r) and "deeper" in path(r)


def test_a_label_outside_the_menu_cannot_be_chosen():
    gw = scripted([{"stage": "classify", "json": {"label": "rm_rf", "confidence": 1.0, "reason": "asked for"}}])
    events = list(service(gw=gw, planner="auto", planner_config={}).stream_ask("Use the rm_rf planner please", ctx()))
    chosen = [(e["planner"], e["by"]) for e in events if e["type"] == "planner_chosen"]
    assert chosen[1] == ("react", "default")
    assert any("did not validate" in c for c in events[-1]["result"]["caveats"])


def test_menu_is_intersected_with_planner_choices():
    from sajha.ai.planners_engine.runtime import GraphPlanner
    reg = get_registry()
    p = reg.build("auto", choices=["reflect"])
    assert isinstance(p, GraphPlanner)
    r = service().ask(MULTI, ctx(), planner="auto", planner_info={"choices": ["reflect"], "tool": "t"})
    assert ">reflect" in r.planner


# ── ask_user: needs_input and MRTR ───────────────────────────────

ASK_DOC = doc(start="clarify", stages={
    "clarify": {"type": "ask_user", "kind": "choice", "message": "Which period for {{question}}?",
                "options": ["2024", "2025"], "outcomes": {"answered": {"next": "act"}, "declined": {"next": "act"}}},
    "act": {"type": "act", "outcomes": {"called": {"next": "act", "max_visits": "steps"}, "answered": {"next": "answer"}}},
    "answer": {"type": "answer"}})
INLINE = {"inline_defaults": {"name": "asker", "version": "1.0.0"}}


def test_ask_user_ends_needs_input_without_mrtr():
    r = service().ask(PCT, ctx(), planner=ASK_DOC, planner_info=INLINE)
    assert r.stopped_by == "needs_input"
    assert r.input_request == {"message": f"Which period for {PCT}?", "kind": "choice", "options": ["2024", "2025"]}


def test_ask_user_uses_mrtr_on_2026_and_resumes_at_its_outcome():
    from sajha.core.mcp_mrtr import InputRequired
    from sajha.core.mcp_tool_context import ModernToolContext
    svc = service()
    mctx = ModernToolContext(client_capabilities={"elicitation": {}})
    tok = mctx.activate()
    try:
        with pytest.raises(InputRequired) as ir:
            svc.ask(PCT, ctx(), planner=ASK_DOC, planner_info=INLINE)
    finally:
        ModernToolContext.deactivate(tok)
    req = ir.value.requests["sajha_planner"]
    assert req["method"] == "elicitation/create" and req["params"]["requestedSchema"]["properties"]["reply"]["enum"] == \
        ["2024", "2025"]
    retry = ModernToolContext(client_capabilities={"elicitation": {}}, state=ir.value.state,
                              input_responses={"sajha_planner": {"action": "accept", "content": {"reply": "2025"}}})
    tok = retry.activate()
    try:
        r = svc.ask(PCT, ctx(), planner=ASK_DOC, planner_info=INLINE)
    finally:
        ModernToolContext.deactivate(tok)
    assert r.stopped_by == "answer" and path(r) == ["clarify", "act", "act", "answer"]
    assert "Clarification: 2025" in json.dumps([s.arguments for s in r.steps]) or r.steps


def test_human_in_the_loop_asks_when_ambiguous():
    r = service(planner="human_in_the_loop").ask("Is this ambiguous: the percentage change from 80 to 100?", ctx())
    assert r.stopped_by == "needs_input" and path(r) == ["clarity", "clarify"] and r.input_request["kind"] == "text"


# ── resolution: LLM tools and Ask SAJHA (§9.12) ──────────────────

def _tool(llm, name="t_llm"):
    from sajha.ai.llm_tools import LLMTool
    cfgd = {"name": name, "implementation": "sajha.ai.llm_tools.LLMTool", "description": "A test LLM tool.",
            "version": "2.0.0",
            "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
            "outputSchema": {"type": "object", "properties": {"answer": {"type": "string"}, "stopped_by": {"type": "string"}}},
            "llm": {"mode": "answer", "tools": {"allow": ["calc_*"]}, **llm}}
    t = LLMTool(cfgd)
    box, gw = ToolBox(), make_gateway()
    t.registry, t.gateway = box, gw
    t.service = IntelligenceService(gw, box, settings=AskSettings(audit=False), audit=lambda e: None)
    return t


ADMIN = RequestContext(user_id="", roles=["admin"], is_admin=True)


@pytest.fixture
def llm_settings(tmp_path):
    from sajha.ai.llm_tools import LLMToolSettings, set_settings
    from sajha.ai.llm_tools.config import SpoolSettings
    from sajha.ai.llm_tools.runtime import Runtime, set_runtime
    s = LLMToolSettings(spool=SpoolSettings(dir=str(tmp_path / "spool")))
    set_settings(s)
    set_runtime(Runtime(s))
    yield
    set_runtime(None)
    set_settings(None)


def test_resolution_order_for_llm_tools(llm_settings):
    q = {"question": PCT}
    assert _tool({}).run(q, ctx=ADMIN, audit=False).planner_by == "server default"
    t = _tool({"planner": "plan_execute@1.0.0", "planner_choices": ["react", "reflect"]})
    assert t.input_schema["properties"]["planner"]["enum"] == ["react", "reflect"]
    info = t.run(q, ctx=ADMIN, audit=False)
    assert (info.planner, info.planner_by, info.planner_version) == ("plan_execute", "tool config", "1.0.0")
    info = t.run({**q, "planner": "reflect"}, ctx=ADMIN, audit=False)
    assert (info.planner, info.planner_by) == ("reflect", "caller choice") and "critique" in info.planner_path
    with pytest.raises(Exception, match="planner"):
        t.execute_with_tracking({**q, "planner": "auto"})            # outside the enum: argument validation
    t._sajha_version_of = "t_llm"                                  # a routed tool version wins
    assert t.run({**q, "planner": "reflect"}, ctx=ADMIN, audit=False).planner_by == "version route"


def test_without_planner_choices_there_is_no_planner_argument(llm_settings):
    assert "planner" not in _tool({"planner": "react"}).input_schema["properties"]


def test_inline_planner_and_overlay_in_a_tool(llm_settings):
    inline = {"description": "One call then answer.", "use_when": "Tests.", "start": "act", "stages": {
        "act": {"type": "act", "outcomes": {"called": {"next": "draft"}, "answered": {"next": "answer"}}},
        "draft": {"type": "draft", "next": "answer"}, "answer": {"type": "answer"}}}
    info = _tool({"planner": inline}).run({"question": PCT}, ctx=ADMIN, audit=False)
    assert info.planner == "t_llm__inline" and info.planner_version == "2.0.0"
    assert info.planner_path == ["act", "draft", "answer"]
    over = {"use": "recipes", "settings": {"fallback": "plan_execute"}}
    info = _tool({"planner": over}).run({"question": MULTI}, ctx=ADMIN, audit=False)
    assert info.planner == "recipes>plan_execute"


def test_ai_ask_planner_maps_onto_the_registry():
    with pytest.raises(ValueError, match="unknown planner"):
        service(planner="nope")
    with pytest.raises(ValueError, match="ai.ask.planner_config.plan_execute"):
        service(planner="plan_execute", planner_config={"plan_execute": {"bogus": 1}})
    r = service(planner="plan_execute@1.0.0").ask(PCT, ctx())
    assert r.planner == "plan_execute" and r.planner_version == "1.0.0"


def test_audit_record_names_planner_version_and_path():
    seen = []
    svc = IntelligenceService(make_gateway(), ToolBox(), settings=AskSettings(planner="reflect"), audit=seen.append)
    svc.ask(PCT, ctx())
    assert seen[0]["planner"] == "reflect" and seen[0]["planner_version"] == "1.0.0"
    assert seen[0]["planner_path"] == ["act", "act", "draft", "critique", "answer"]


# ── validation rules (§12) ───────────────────────────────────────

@pytest.mark.parametrize("d,code", [
    ([1, 2], "P001"),
    (doc(name="Bad Name"), "P002"),
    (doc(version="1.0"), "P003"),
    (doc(extra=1), "P004"),
    (doc(stages={"act": {"type": "dance", "next": "answer"}, "answer": {"type": "answer"}}), "P010"),
    (doc(stages={"act": {"type": "act", "next": "answer", "tool_choice": "maybe"}, "answer": {"type": "answer"}}), "P011"),
    (doc(start="nowhere"), "P012"),
    (doc(stages={"act": {"type": "act", "next": "answer"}, "answer": {"type": "answer"},
                 "lost": {"type": "answer"}}), "P013"),
    (doc(stages={"act": {"type": "act", "outcomes": {"called": {"next": "answer"}}}, "answer": {"type": "answer"}}), "P014"),
    (doc(stages={"act": {"type": "act", "next": "elsewhere"}, "answer": {"type": "answer"}}), "P015"),
    (doc(stages={"act": {"type": "act", "outcomes": {"called": {"next": "answer"}, "answered": {"next": "answer"},
                                                     "pass": {"next": "answer"}}}, "answer": {"type": "answer"}}), "P016"),
    (doc(stages={"act": {"type": "act", "next": "answer"}, "answer": {"type": "answer", "next": "act"}}), "P017"),
    (doc(stages={"act": {"type": "act", "outcomes": {"called": {"next": "act"}, "answered": {"next": "answer"}}},
                 "answer": {"type": "answer"}}), "P020"),
    (doc(stages={"act": {"type": "act", "outcomes": {"called": {"next": "act", "max_visits": 2},
                                                     "answered": {"next": "answer"}}}, "answer": {"type": "answer"}}), "P011"),
    (doc(stages={"act": {"type": "draft", "outcomes": {"done": {"next": "act", "max_visits": "steps"}}},
                 "answer": {"type": "answer"}}, start="act"), "P022"),
    (doc(stages={"act": {"type": "act", "model": "critic", "next": "answer"}, "answer": {"type": "answer"}}), "P030"),
    (doc(models={"critic": "no_such_alias"}), "P031"),
    (doc(stages={"act": {"type": "act", "prompt": "missing", "next": "answer"}, "answer": {"type": "answer"}}), "P032"),
    (doc(stages={"act": {"type": "planner", "planner": "{{chosen}}", "next": "answer"}, "answer": {"type": "answer"}}), "P037"),
    (doc(stages={"act": {"type": "act", "next": "answer"}, "answer": {"type": "answer", "when": "len(", "else": {"next": "act"}}}), "P040"),
    (doc(stages={"act": {"type": "act", "next": "answer"}, "answer": {"type": "answer", "when": "nosuch > 1", "else": {"next": "act"}}}), "P041"),
    (doc(stages={"act": {"type": "act", "next": "answer"}, "answer": {"type": "answer", "when": "'a' < 1", "else": {"next": "act"}}}), "P042"),
    (doc(stages={"act": {"type": "act", "next": "answer"}, "answer": {"type": "answer", "template": "{{nosuch}}"}}), "P043"),
    (doc(settings={}, stages={"act": {"type": "act", "next": "answer"},
                              "answer": {"type": "answer", "synthesize": "{{settings.missing}}"}}), "P011"),
    (doc(stages={"m": {"type": "match", "rules": [{"name": "r", "pattern": "("}], "outcomes": {"*": {"next": "answer"}}},
                 "answer": {"type": "answer"}}, start="m"), "P045"),
    (doc(state={"draft": {"type": "string"}}), "P050"),
    (doc(stages={"m": {"type": "match", "rules": [{"name": "r", "pattern": "x"}], "into": "nowhere",
                       "outcomes": {"*": {"next": "answer"}}}, "answer": {"type": "answer"}}, start="m"), "P051"),
    (doc(stages={"act": {"type": "act", "next": "answer", "set": {"question": "'x'"}}, "answer": {"type": "answer"}}), "P052"),
    (doc(settings={"rules": []}, stages={"m": {"type": "match", "rules": "{{settings.rules}}",
                                              "outcomes": {"none": {"next": "answer"}}}, "answer": {"type": "answer"}},
         start="m"), "P062"),
    (doc(stages={"act": {"type": "act", "outcomes": {"called": {"next": "act", "max_visits": "steps"},
                                                     "answered": {"next": "loop"}}},
                 "loop": {"type": "verify", "checks": ["length"], "outcomes": {"ok": {"next": "loop2", "max_visits": 1,
                                                                                      "on_exhausted": "loop2"},
                                                                               "mismatch": {"next": "loop2"}}},
                 "loop2": {"type": "draft", "outcomes": {"done": {"next": "loop", "max_visits": 1, "on_exhausted": "loop"}}},
                 "answer": {"type": "answer"}}), "P063"),
])
def test_validation_rules(d, code):
    assert code in codes(d, check_alias=lambda a: a in ("default", "fast", "reasoning"))


@pytest.mark.parametrize("d,code", [
    (doc(stages={"act": {"type": "act", "outcomes": {"called": {"next": "act", "max_visits": 99, "on_exhausted": "answer"},
                                                     "answered": {"next": "answer"}}}, "answer": {"type": "answer"}}), "P023"),
    (doc(stages={"act": {"type": "act", "outcomes": {"called": [{"next": "answer", "when": "true"}],
                                                     "answered": {"next": "answer"}}}, "answer": {"type": "answer"}}), "P016"),
    (doc(stages={"m": {"type": "match", "rules": [{"name": "r", "pattern": "(a+)+$"}], "outcomes": {"*": {"next": "answer"}}},
                 "answer": {"type": "answer"}}, start="m"), "P046"),
    (doc(limits={"max_stages_run": 999}), "P060"),
])
def test_warnings_load_the_file(d, code):
    got = codes(d)
    assert code in got and "OK" in got


def test_sub_planner_rules_need_the_registry(registry):
    missing = doc(stages={"act": {"type": "planner", "planner": "no_such", "next": "answer"}, "answer": {"type": "answer"}})
    assert {d.code for d in registry.link(compile_planner(missing), {})} >= {"P033"}
    pinned = doc(stages={"act": {"type": "planner", "planner": "react", "next": "answer"}, "answer": {"type": "answer"}})
    assert "P071" in {d.code for d in registry.link(compile_planner(pinned), {})}
    with pytest.raises(PlannerError) as e:                               # a router rule naming router: a cycle
        registry.compiled("router", {"router": {"settings": {"rules": [{"match": "x", "planner": "router"}]}}})
    assert "P034" in e.value.codes
    deep = doc(name="deep", stages={"act": {"type": "planner", "planner": "auto", "next": "answer"},
                                    "answer": {"type": "answer"}})
    assert "P035" in {d.code for d in registry.link(compile_planner(deep), {})}


def test_python_kind_files_and_p061():
    good = {"name": "pyreact", "version": "1.0.0", "kind": "python", "class": "sajha.ai.planners:ReactPlanner",
            "description": "React in Python.", "use_when": "Tests."}
    assert compile_planner(good).cls.__name__ == "ReactPlanner"
    bad = dict(good, **{"class": "sajha.ai.planners:Nope"})
    assert "P061" in codes(bad)
    assert "P004" in codes(dict(good, start="x"))


# ── YAML safety (P006) ───────────────────────────────────────────

def test_a_bare_on_key_and_unquoted_yes_are_refused():
    text = """
name: t
version: 1.0.0
description: d
use_when: u
start: c
stages:
  c:
    type: classify
    labels: [yes, no]
    on: { "true": { next: a } }
  a: { type: answer }
"""
    d = yaml.safe_load(text)
    with pytest.raises(PlannerError) as e:
        compile_planner(d)
    msgs = str(e.value)
    assert set(e.value.codes) == {"P006"} and "a bare on: loads as true" in msgs and "quote it" in msgs
    quoted = yaml.safe_load(text.replace("[yes, no]", '["yes", "no"]').replace(
        'on: { "true": { next: a } }', 'outcomes: { "yes": { next: a }, "no": { next: a } }'))
    assert compile_planner(quoted).stages["c"].outcomes.keys() == {"yes", "no"}


# ── the expression language (§8) ─────────────────────────────────

def _env(state):
    return E.Env(lambda r: state.get(r), lambda: state, visits=lambda s: 2, offered=lambda t: t == "calc")


@pytest.mark.parametrize("text,value", [
    ("len(plan) > 0 and plan[0].ok", True),
    ("'parts_answered' in $.findings[*].check", True),
    ("false in $.results[*].ok", True),
    ("not exists(missing.deep[3])", True),
    ("choice.confidence >= 0.5 or chosen == 'react'", True),
    ("number('1,234.5') == 1234.5", True),
    ("matches(lower(q), 'hello')", True),
    ("visits('act') == 2 and offered('calc')", True),
    ("plan[-1].ok != true", True),
    ("[1, 2] == [1.0, 2]", True),
    ("'ell' in q and 'x' not in q", True),
    ("empty(missing) and empty('') and not empty(plan)", True),
])
def test_expressions(text, value):
    state = {"plan": [{"ok": True}, {"ok": False}], "findings": [{"check": "parts_answered"}],
             "results": [{"ok": True}, {"ok": False}], "choice": {"confidence": 0.7}, "chosen": "x", "q": "Hello"}
    ex = E.compile_expression(text, set(state) | {"missing"}, {"act"})
    assert E.evaluate(ex, _env(state)) is value


@pytest.mark.parametrize("text,error", [
    ("a < b < c", E.ExprSyntaxError), ("a +", E.ExprSyntaxError), ("$.a[?(@.x)]", E.ExprSyntaxError),
    ("os.system('x')", E.ExprSyntaxError), ("len()", E.ExprNameError), ("len(3)", E.ExprTypeError),
    ("__import__('os')", E.ExprNameError),
])
def test_expression_errors_at_load(text, error):
    with pytest.raises(error):
        E.compile_expression(text, {"a", "b", "c"})


def test_runtime_type_errors_make_the_condition_false():
    d = doc(stages={"act": {"type": "act", "outcomes": {"called": {"next": "act", "max_visits": "steps"},
                                                        "answered": [{"next": "answer", "when": "draft > 3"},
                                                                     {"next": "answer"}]}},
                    "answer": {"type": "answer"}})
    events = list(service().stream_ask(PCT, ctx(), planner=d, planner_info=INLINE))
    errs = [e for e in events if e["type"] == "expression_error"]
    assert errs and errs[0]["expression"] == "draft > 3" and events[-1]["result"]["stopped_by"] == "answer"


def test_templates_keep_the_type_of_a_whole_value():
    get = {"groups": {"n": 5}, "q": "x"}.get
    assert E.render("{{groups.n}}", get, keep_type=True) == 5
    assert E.render("n={{groups.n}} {{state.q}}", get) == "n=5 x"


# ── registry: versions, pins, reload with last-good fallback ──────

def test_versions_pins_and_last_good_fallback(tmp_path):
    from sajha.core.storage import LocalStorageBackend
    d = tmp_path / "planners"
    d.mkdir()
    one = doc(name="mine", version="1.0.0")
    (d / "mine@1.0.0.yaml").write_text(yaml.safe_dump(one))
    (d / "mine.yaml").write_text(yaml.safe_dump(dict(one, version="1.1.0")))
    reg = PlannerRegistry(storage=LocalStorageBackend(str(tmp_path)), settings=PlannerSettings(dir="planners",
                                                                                               reload_interval_s=0))
    assert reg.entry("mine").version == "1.1.0" and reg.entry("mine@1.0.0").version == "1.0.0"
    assert reg.entry("mine@latest").version == "1.1.0"
    with pytest.raises(ValueError, match="not found"):
        reg.entry("mine@9.9.9")
    import time
    time.sleep(0.01)
    (d / "mine.yaml").write_text(yaml.safe_dump(dict(one, version="1.1.0", start="nowhere")))
    os.utime(d / "mine.yaml", (time.time() + 5, time.time() + 5))
    assert reg.entry("mine").version == "1.1.0" and "mine.yaml" in reg.errors       # the last good stays
    (d / "mine@1.0.0.yaml").write_text(yaml.safe_dump(dict(one, name="other")))
    os.utime(d / "mine@1.0.0.yaml", (time.time() + 9, time.time() + 9))
    reg.entry("mine")
    assert "P002" in [x.code for x in reg.errors["mine@1.0.0.yaml"]]


def test_duplicate_name_and_version_is_p005(tmp_path):
    from sajha.core.storage import LocalStorageBackend
    d = tmp_path / "planners"
    d.mkdir()
    (d / "a.yaml").write_text(yaml.safe_dump(doc(name="a")))
    (d / "a@1.0.0.yaml").write_text(yaml.safe_dump(doc(name="a")))
    reg = PlannerRegistry(storage=LocalStorageBackend(str(tmp_path)), settings=PlannerSettings(dir="planners"))
    reg.load()
    assert [x.code for x in reg.errors["a@1.0.0.yaml"]] == ["P005"]


# ── custom stage types (admin, code) ─────────────────────────────

def test_a_custom_stage_type_is_validated_and_runs():
    from sajha.ai.planners_engine import StageType

    class Gate(StageType):
        name = "confidence_gate"
        fixed_outcomes = ("ok", "low")
        settings_schema = {"type": "object", "properties": {"below": {"type": "number"}}}

        def run(self, rc, frame, st):
            return "low" if rc.lookup(frame)("confidence") < float(st.cfg.get("below", 0.6)) else "ok"

    register_stage_type(Gate)
    try:
        d = doc(stages={"act": {"type": "act", "outcomes": {"called": {"next": "act", "max_visits": "steps"},
                                                            "answered": {"next": "gate"}}},
                        "gate": {"type": "confidence_gate", "below": 0.9,
                                 "outcomes": {"ok": {"next": "answer"}, "low": {"next": "answer"}}},
                        "answer": {"type": "answer"}})
        r = service().ask(PCT, ctx(), planner=d, planner_info=INLINE)
        assert "gate" in path(r) and r.stopped_by == "answer"
        assert "P011" in codes(dict(d, stages=dict(d["stages"], gate=dict(d["stages"]["gate"], colour="red"))))
    finally:
        unregister_stage_type("confidence_gate")
    assert "P010" in codes(d)


# ── the dry-run endpoint and the planner list ─────────────────────

def _client(monkeypatch, admin=True):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sajha.ai import gateway as gwmod, intelligence
    from sajha.auth import AuthContext, require_admin, require_auth
    from sajha.routes.ai_routes import router
    gw = make_gateway()
    monkeypatch.setattr(gwmod, "_gateway", gw)
    monkeypatch.setattr(intelligence, "_service", service(ToolBox(), gw))
    app = FastAPI()
    app.include_router(router)
    who = AuthContext(authenticated=True, user_id="admin" if admin else "bob", roles=["admin" if admin else "user"],
                      is_admin=admin)
    app.dependency_overrides[require_auth] = lambda: who
    if admin:
        app.dependency_overrides[require_admin] = lambda: who
    return TestClient(app)


def test_dry_run_returns_the_stage_path(monkeypatch):
    c = _client(monkeypatch)
    body = c.post("/api/ai/planners/dry-run", json={"planner": "reflect", "question": PCT}).json()
    assert body["path"] == ["act", "draft", "critique", "answer"] or body["path"][0] == "act"
    assert body["planner"] == "reflect" and body["stopped_by"] == "answer"
    assert c.post("/api/ai/planners/dry-run", json={"planner": "nope", "question": PCT}).status_code == 400
    names = {p["name"] for p in c.get("/api/ai/planners").json()["planners"]}
    assert set(SHIPPED) <= names
    assert c.get("/api/ai/planners/reflect").json()["stages"]["critique"]["type"] == "critique"


def test_dry_run_runs_only_read_only_tools_and_those_named(monkeypatch):
    from sajha.ai.planners_engine.dryrun import read_only
    assert read_only(FakeTool("x", "y")) is False
    c = _client(monkeypatch)
    body = c.post("/api/ai/planners/dry-run", json={"planner": "react", "question": PCT}).json()
    assert body["tool_calls"] == [{"name": "calc_percentage_change", "ok": False, "run": False}]
    body = c.post("/api/ai/planners/dry-run", json={"planner": "react", "question": PCT,
                                                    "run_tools": ["calc_percentage_change"]}).json()
    assert body["tool_calls"] == [{"name": "calc_percentage_change", "ok": True, "run": True}] and "25" in body["answer"]


def test_dry_run_is_for_admins(monkeypatch):
    from sajha.auth import require_admin
    c = _client(monkeypatch, admin=False)
    r = c.post("/api/ai/planners/dry-run", json={"planner": "react", "question": PCT})
    assert r.status_code in (401, 403)


# ── metrics ──────────────────────────────────────────────────────

def test_planner_metrics_are_recorded():
    from sajha.observability.metrics import REGISTRY
    service(planner="reflect").ask(PCT, ctx())
    assert REGISTRY.family("sajha_planner_stages_total").value(("reflect", "critique", "pass")) >= 1
    assert REGISTRY.family("sajha_planner_chosen_total").value(("ask", "reflect", "server")) >= 1


def test_p036_planner_tools_must_be_allowed_by_the_tool(llm_settings):
    from sajha.ai.llm_tools.config import catalog_problems
    inline = {"description": "d", "use_when": "u", "start": "c", "stages": {
        "c": {"type": "call", "tool": "files_delete_everything", "next": "a"}, "a": {"type": "answer"}}}
    t = _tool({"planner": inline})
    assert any("P036" in p and "files_delete_everything" in p for p in catalog_problems(t.spec, t.name, t.registry))
    ok = dict(inline, stages={"c": {"type": "call", "tool": "calc_percentage_change", "next": "a"}, "a": {"type": "answer"}})
    t = _tool({"planner": ok})
    assert not [p for p in catalog_problems(t.spec, t.name, t.registry) if "P036" in p]


def test_tutorial_27_planner_loads_and_takes_the_paths_it_shows(tmp_path):
    """docs/tutorials/TUTORIAL_27_write_a_planner.md: the file it writes, and the paths it promises."""
    import re
    import shutil
    from sajha.ai.planners_engine.dryrun import dry_run
    from sajha.core.storage import LocalStorageBackend
    text = open("docs/tutorials/TUTORIAL_27_write_a_planner.md").read()
    body = re.search(r"Create the file `pct_desk.yaml` in `config/planners/`:\n\n```yaml\n(.*?)```", text, re.S).group(1)
    d = tmp_path / "planners"
    d.mkdir()
    for f in glob.glob("config/planners/*.yaml"):
        shutil.copy(f, d)
    (d / "pct_desk.yaml").write_text(body)
    reg = PlannerRegistry(storage=LocalStorageBackend(str(tmp_path)), settings=PlannerSettings(dir="planners"))
    set_registry(reg)
    assert reg.entry("pct_desk").version == "1.0.0" and not reg.errors and not reg.entry("pct_desk").warnings
    admin = RequestContext(user_id="admin", is_admin=True)
    out = dry_run(service(), "pct_desk", "What is the percent change from 80 to 100?", admin,
                  run_tools=["calc_percentage_change"])
    assert out["path"] == ["shape", "compute", "done"] and out["answer"] == "From 80 to 100 is a change of 25.0%."
    out = dry_run(service(), "pct_desk", "What is the future value of 5000 at 7 percent for 20 years?", admin,
                  run_tools=["calc_future_value"])
    assert out["path"] == ["shape", "general", "check", "answer"] and "pct_desk>react/act" in out["trace"]
    out = dry_run(service(), "pct_desk", "What is the percent change from 80 to 100?", admin)
    assert out["path"] == ["shape", "compute", "general", "check", "answer"]
    broken = yaml.safe_load(body)
    broken["stages"]["check"]["outcomes"]["mismatch"] = {"next": "fix"}
    with pytest.raises(PlannerError, match=r"unbounded cycle: check -> fix -> check"):
        compile_planner(broken)
