# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The numbers validator and the numbers_check setting (docs/architecture/Quantitative Planners.md
§2.4, §2.5; Planner Reference §9.1): numbers_in_results' own cases run against both checks,
workspace matching in convertible units, the verify stage reading the run's workspace, the
reserved setting (validation, default, overlay) and warn/enforce on the mock provider."""

import pytest

from sajha.ai.intelligence import IntelligenceService
from sajha.ai.llm import RequestContext
from sajha.ai.llm.settings import AskSettings
from sajha.ai.planners_engine import (PlannerError, PlannerRegistry, StageType, compile_planner, get_registry,
                                      register_stage_type, set_registry, unregister_stage_type)
from sajha.ai.planners_engine.checks import CheckContext, checks
from sajha.ai.planners_engine.model import apply_overlay
from sajha.ai.planners_engine.settings import PlannerSettings, load_settings
from sajha.ai.quant import Quantity, Workspace, ops, workspace_of
from tests.ai.conftest import ToolBox, make_gateway

PCT = "What is the percentage change from 80 to 100?"
CALL = {"tool_calls": [{"name": "calc_percentage_change", "arguments": {"old_value": 80, "new_value": 100}}]}
BOTH = ["numbers_in_results", "numbers_in_workspace"]


@pytest.fixture(autouse=True)
def registry():
    reg = PlannerRegistry()
    set_registry(reg)
    yield reg
    set_registry(None)


def run_check(name, draft, results=(), question="", workspace=None, **settings):
    ctx = CheckContext(draft=draft, draft_json=None, citations=[], question=question,
                       results=[{"id": f"c{i}", "ok": True, "data": d} if not isinstance(d, tuple) else
                                {"id": f"c{i}", "ok": d[1], "data": d[0]} for i, d in enumerate(results)],
                       output_schema=None, lookup=lambda r: None, evaluate=lambda e: True, workspace=workspace)
    return checks()[name](ctx, settings)


# ── numbers_in_results' own cases (§9.1), against both checks ────

@pytest.mark.parametrize("check", BOTH)
@pytest.mark.parametrize("draft,data,ok", [
    ("The price is 123.45.", {"price": 123.45}, True),
    ("About 100.4 units.", {"n": 100.0}, True),                       # relative tolerance 0.005
    ("About 101.5 units.", {"n": 100.0}, False),
    ("The change is 31.7.", {"v": 31.66667}, True),                    # rounded to the draft's places
    ("Margin was 25%.", {"m": 0.25}, True),                            # d / 100
    ("Margin was 25%.", {"m": 25}, False),                           # a bare 25 is not 25 percent (§2.4)
    ("Margin was 25%.", {"margin_pct": 25}, True),                     # a result known to be in percent
    ("Margin was 25%.", {"margin": {"value": 25, "format": "percent"}}, True),
    ("Margin was 25%.", {"text": "a margin of 25% in 2025"}, True),
    ("Margin was 25 percent.", {"m": 25}, False),
    ("Revenue was 1.2 billion.", {"r": 1200000000}, True),             # scale word
    ("Revenue was 1.2 billion.", {"r": 1.2}, True),                    # the unscaled mantissa
    ("Revenue was 4.5 bn.", {"text": "revenue of 4.5 bn in 2025"}, True),   # numbers inside strings
    ("Total 1,234,567.", {"t": 1234567}, True),                        # thousands separators
    ("Total 1,234,567.", {"t": 1234568}, True),
    ("Total 12.7.", {"t": 13.9}, False),
])
def test_numbers_in_results_cases(check, draft, data, ok):
    assert (run_check(check, draft, [data]) == []) is ok


@pytest.mark.parametrize("check", BOTH)
def test_ignore_rules(check):
    assert run_check(check, "From 80 to 100 is 25.", [{"v": 25}], question=PCT) == []
    assert run_check(check, "In 2024 there were 3 of them.", []) == []
    assert run_check(check, "1. first 12.5\n2. second", [{"v": 12.5}]) == []
    assert len(run_check(check, "From 80 to 100.", [], question=PCT, ignore=[])) == 2


@pytest.mark.parametrize("check", BOTH)
def test_failures_and_limits(check):
    f = run_check(check, "It was 12.7.", [])
    assert len(f) == 1 and f[0]["value"] == 12.7 and f[0]["check"] == check and "12.7" in f[0]["message"]
    assert len(run_check(check, "Values 11.1, 12.2 and 13.3.", [], max_numbers=2)) == 2
    assert len(run_check(check, "It was 12.7.", [({"v": 12.7}, False)])) == 1     # a failed call is no evidence
    assert run_check(check, "It was 12.9.", [{"v": 12.7}], tolerance=0.02) == []


def test_numbers_in_workspace_is_registered_and_usable_in_a_planner_file():
    assert "numbers_in_workspace" in checks()
    d = {"name": "t", "version": "1.0.0", "description": "d", "use_when": "u", "start": "draft",
         "stages": {"draft": {"type": "draft", "next": "verify"},
                    "verify": {"type": "verify", "checks": ["numbers_in_workspace",
                                                            {"check": "numbers_in_workspace", "tolerance": 0.01}],
                               "outcomes": {"ok": {"next": "answer"}, "mismatch": {"next": "answer"}}},
                    "answer": {"type": "answer"}}}
    assert compile_planner(d).name == "t"


# ── workspace matching (§2.4) ────────────────────────────────────

def spread_ws():
    ws = Workspace()
    ws.put("spread", ops.bp_spread(Quantity.of(4.10, "percent"), Quantity.of(3.65, "percent")))   # 45 bp
    return ws


@pytest.mark.parametrize("draft,ok", [
    ("The spread is 45 bp.", True), ("The spread is 45bps.", True), ("The spread is 45 basis points.", True),
    ("The spread is 0.45%.", True), ("The spread is 0.45 percent.", True), ("The spread is 45.", True),
    ("The spread is 0.45 pp.", True), ("The spread as a decimal is 0.0045.", True), ("Spread (in bp): 45.", True),
    ("The spread is 45%.", False), ("The spread is 0.45 bp.", False), ("The spread is 46 bp.", False),
    ("The spread is 0.0045.", False),                                  # a bare figure: the quantity's own unit only
])
def test_a_bp_spread_matches_in_every_rate_unit(draft, ok):
    assert (run_check("numbers_in_workspace", draft, workspace=spread_ws()) == []) is ok
    if ok and draft != "The spread is 45.":
        assert run_check("numbers_in_results", draft) != []           # no tool result has it


@pytest.mark.parametrize("draft,ok", [
    ("Inflation was 4.5%.", True), ("Inflation was 450 bp.", True), ("Inflation was 4.5.", True),
    ("Inflation, in bp, was 450.", True),
    ("Inflation was 450.", False),                                     # not 4.5% read as 450 bp
    ("Inflation was 0.045.", False),                                   # nor as a ratio, unless the text says so
])
def test_a_bare_figure_does_not_match_every_convertible_unit(draft, ok):
    ws = Workspace()
    ws.put("infl", Quantity.of(4.5, "percent"))
    assert (run_check("numbers_in_workspace", draft, workspace=ws) == []) is ok


def test_a_percent_figure_does_not_match_a_bare_result_number():
    ws = Workspace()
    ws.put("count", Quantity.of(25, "count"))
    assert len(run_check("numbers_in_workspace", "Up 25%.", [{"n": 25}], workspace=ws)) == 1
    assert run_check("numbers_in_workspace", "Up 25%.", [{"growth_pct": 25}], workspace=ws) == []
    assert run_check("numbers_in_workspace", "Up 25%.", [{"n": 0.25}], workspace=ws) == []   # a ratio x 100


def test_precision_written_and_currency_scales():
    ws = Workspace()
    ws.put("infl", ops.pct_change(Quantity.of(298.1, "index"), Quantity.of(310.3, "index")))   # 4.0925...%
    ws.put("rev", Quantity.of(1.5e9, "USD"))
    ws.put("diff", ops.diff(Quantity.of(4.10, "percent"), Quantity.of(2.65, "percent")))         # 1.45 pp
    ws.put("table", Quantity.of([[11.25, 12.5], [13.75, 15.0]], "USD mn"))
    for good in ["Inflation was 4.09%.", "Inflation was 4.1%.", "Revenue was 1.5 bn.", "Revenue was 1,500 million.",
                 "Revenue was 1500000000.", "It rose 1.45 percentage points.", "It rose 145 bp.", "A cell: 13.75."]:
        assert run_check("numbers_in_workspace", good, workspace=ws) == [], good
    for bad in ["Inflation was 4.2%.", "Revenue was 1.6 bn.", "It rose 1.55 pp.", "A cell: 13.9."]:
        assert len(run_check("numbers_in_workspace", bad, workspace=ws)) == 1, bad


def test_without_a_workspace_it_is_numbers_in_results():
    for draft in ["It is 25%.", "It is 31.7.", "1.2 billion"]:
        a = run_check("numbers_in_results", draft, [{"v": 25}])
        b = run_check("numbers_in_workspace", draft, [{"v": 25}])
        assert [f["value"] for f in a] == [f["value"] for f in b]


# ── the reserved setting (§2.5) ──────────────────────────────────

BASE = {"name": "t", "version": "1.0.0", "description": "d", "use_when": "u", "start": "answer",
        "stages": {"answer": {"type": "answer"}}}


def test_numbers_check_is_reserved_and_validated():
    for mode in ("off", "warn", "enforce"):
        assert compile_planner(dict(BASE, settings={"numbers_check": mode})).settings["numbers_check"] == mode
        assert apply_overlay(BASE, {"settings": {"numbers_check": mode}}, "o")["settings"]["numbers_check"] == mode
    with pytest.raises(PlannerError) as e:
        compile_planner(dict(BASE, settings={"numbers_check": "strict"}))
    assert "P011" in e.value.codes
    with pytest.raises(ValueError, match="numbers_check"):
        apply_overlay(BASE, {"settings": {"numbers_check": True}}, "o")
    from sajha.ai.planners_engine.model import own_settings
    assert own_settings({"numbers_check": "warn", "x": 1}) == {"x": 1}


def test_the_default_comes_from_ai_planners_numbers_check():
    assert load_settings({}, environ={}).numbers_check == "off"
    assert load_settings({"numbers_check": "warn"}, environ={}).numbers_check == "warn"
    assert load_settings({}, environ={"SAJHA_AI_PLANNERS_NUMBERS_CHECK": "enforce"}).numbers_check == "enforce"


# ── warn and enforce on the mock provider ───────────────────────

def scripted(steps):
    gw = make_gateway({"aliases": {a: ["mock/mock-scripted"] for a in ("default", "fast", "reasoning")},
                       "cache": {"enabled": False}})
    gw.providers["mock"].set_script(steps, mode="ordered")
    return gw


def service(gw, planner="react", planner_config=None):
    settings = AskSettings(audit=False, planner=planner, planner_config=planner_config or {}, synthesize=False)
    return IntelligenceService(gw, ToolBox(), settings=settings)


def ask(gw, mode=None, planner="react", **kw):
    cfg = {planner: {"numbers_check": mode}} if mode and isinstance(planner, str) else {}
    events = list(service(gw, planner, cfg).stream_ask(PCT, RequestContext(user_id="u"), **kw))
    return events[-1]["result"], [e for e in events if e["type"] == "numbers_check"]


def answer(text):
    return {"json": {"answer": text, "citations": [], "caveats": []}}


def test_off_by_default_changes_nothing():
    r, ev = ask(scripted([CALL, {"text": "It changed 25%, or 31.7 units."}]))
    assert r["answer"] == "It changed 25%, or 31.7 units." and not ev
    assert not any("traced" in c for c in r["caveats"])


def test_warn_names_the_unmatched_figures():
    r, ev = ask(scripted([CALL, {"text": "It changed 25%, or 31.7 units."}]), "warn")
    assert r["answer"] == "It changed 25%, or 31.7 units."
    assert any("31.7" in c and "25" not in c.split(":")[1] for c in r["caveats"])
    assert ev[0]["mode"] == "warn" and ev[0]["check"] == "numbers_in_results" and ev[0]["unmatched"] == ["31.7"]


def test_warn_from_the_server_default(registry):
    registry.settings = PlannerSettings(numbers_check="warn")
    registry.invalidate()
    r, ev = ask(scripted([CALL, {"text": "It changed 31.7%."}]))
    assert ev and ev[0]["unmatched"] == ["31.7%"] and any("31.7%" in c for c in r["caveats"])


def test_a_matching_answer_passes_quietly():
    r, ev = ask(scripted([CALL, {"text": "It changed 25%."}]), "enforce")
    assert r["answer"] == "It changed 25%." and ev[0]["unmatched"] == [] and not ev[0]["revised"]


def test_enforce_revises_once_and_the_revision_is_kept_when_it_matches():
    gw = scripted([CALL, {"text": "It changed 31.7%."}, {"stage": "numbers_check", **answer("It changed 25%.")}])
    r, ev = ask(gw, "enforce")
    assert r["answer"] == "It changed 25%." and ev[0]["revised"] and ev[0]["removed"] == []
    assert not any("removed" in c for c in r["caveats"])


def test_enforce_removes_what_still_does_not_match():
    gw = scripted([CALL, {"text": "It changed 25%, or 31.7 units."},
                   answer("It changed 25%, or 33.3 units, a 12.5 bp move.")])
    r, ev = ask(gw, "enforce")
    assert "33.3" not in r["answer"] and "12.5" not in r["answer"] and "25%" in r["answer"]
    assert r["answer"].count("[unverified figure removed]") == 2 and " bp" not in r["answer"]
    assert ev[0]["removed"] == ["33.3", "12.5 bp"]
    assert any("2 figures" in c and "33.3" in c and "removed" in c for c in r["caveats"])


def test_enforce_when_the_revision_fails_still_removes():
    gw = scripted([CALL, {"text": "It changed 31.7%."}, {"text": "not json"}])
    r, ev = ask(gw, "enforce")
    assert "31.7" not in r["answer"] and ev[0]["removed"] == ["31.7%"]


def test_an_overlay_on_an_llm_tool_style_planner_reference():
    gw = scripted([CALL, {"text": "It changed 31.7%."}])
    events = list(service(gw).stream_ask(PCT, RequestContext(user_id="u"),
                                         planner={"use": "react", "settings": {"numbers_check": "warn"}},
                                         planner_info={"overlays": {"react": {"settings": {"numbers_check": "warn"}}},
                                                       "by": "tool config", "tool": "t"}))
    assert [e for e in events if e["type"] == "numbers_check"][0]["mode"] == "warn"


# ── the workspace in a run: the verify stage and the service check ─

class PutSpread(StageType):
    """Test stage: computes a 45 bp spread into the run's workspace."""
    name = "put_spread"
    fixed_outcomes = ("done",)
    settings_schema = {"type": "object"}

    def run(self, rc, frame, st):
        ws = workspace_of(rc.state, create=True)
        ws.run("bp_spread", Quantity.of(4.10, "percent"), Quantity.of(3.65, "percent"), name="spread")
        return "done"
        yield  # pragma: no cover


@pytest.fixture
def put_spread():
    register_stage_type(PutSpread)
    yield
    unregister_stage_type("put_spread")


def quant_planner(verify=False):
    stages = {"act": {"type": "act", "outcomes": {"called": {"next": "act", "max_visits": "steps"},
                                                  "answered": {"next": "quant"}}},
              "quant": {"type": "put_spread", "next": "verify" if verify else "answer"},
              "answer": {"type": "answer"}, "flagged": {"type": "answer"}}
    if verify:
        stages["verify"] = {"type": "verify", "checks": ["numbers_in_workspace"],
                            "outcomes": {"ok": {"next": "answer"}, "mismatch": {"next": "flagged"}}}
    else:
        del stages["flagged"]
    return {"name": "quanty", "version": "1.0.0", "description": "d", "use_when": "u", "start": "act",
            "stages": stages}


INLINE = {"inline_defaults": {"name": "quanty", "version": "1.0.0"}}


@pytest.mark.parametrize("text,stage", [("The spread is 0.45%, 25% overall.", "answer"),
                                        ("The spread is 0.55%.", "flagged")])
def test_the_verify_stage_reads_the_run_workspace(put_spread, text, stage):
    gw = scripted([CALL, {"text": text}])
    r = service(gw).ask(PCT, RequestContext(user_id="u"), planner=quant_planner(verify=True), planner_info=INLINE)
    assert [p for p in r.planner_path if "/" not in p][-1] == stage


def test_the_service_check_uses_the_workspace_when_the_run_has_one(put_spread):
    gw = scripted([CALL, {"text": "The spread is 45 bp (as a decimal 0.0045), and the change 25%; also 9.9 and 0.0045."}])
    p = dict(quant_planner(), settings={"numbers_check": "warn"})
    events = list(service(gw).stream_ask(PCT, RequestContext(user_id="u"), planner=p, planner_info=INLINE))
    ev = [e for e in events if e["type"] == "numbers_check"][0]
    assert ev["check"] == "numbers_in_workspace" and ev["unmatched"] == ["9.9", "0.0045"]


def test_a_bare_yaml_off_is_off():
    import yaml
    doc = yaml.safe_load("numbers_check: off")
    assert doc["numbers_check"] is False
    assert compile_planner(dict(BASE, settings=doc)).name == "t"
    assert load_settings(doc, environ={}).numbers_check == "off"
    from sajha.ai.planners_engine.numbers import mode_for
    assert mode_for(doc, "warn") == "off" and mode_for({}, "warn") == "warn"


def test_the_run_record_keeps_the_workspace(put_spread):
    gw = scripted([CALL, {"text": "The spread is 45 bp."}])
    r = service(gw).ask(PCT, RequestContext(user_id="u"), planner=quant_planner(), planner_info=INLINE)
    q = r.to_dict()["workspace"]["quantities"][0]
    assert q["name"] == "spread" and q["value"] == pytest.approx(45) and q["unit"] == "bp"
    assert q["lineage"]["op"] == "bp_spread"
    plain = service(scripted([CALL, {"text": "25%"}])).ask(PCT, RequestContext(user_id="u"))
    assert plain.workspace is None
