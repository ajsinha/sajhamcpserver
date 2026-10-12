# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Planners chosen by learning from results (LLM Tools §9.13, Planner Reference §6.6.2): question
classes, ranking from synthetic outcomes, evidence from eval runs and audit records, proposal ->
approval -> effect -> rollback, and the opt-in bandit (bounds, permissions, filters, kill switch,
guard, determinism with a seed)."""

import json

import pytest

from sajha.ai.intelligence import IntelligenceService
from sajha.ai.llm import RequestContext
from sajha.ai.llm.settings import AskSettings
from sajha.ai.planners_engine import PlannerRegistry, set_registry
from sajha.ai.planners_engine import learning as L
from sajha.ai.planners_engine.settings import PlannerLearningSettings, PlannerSettings
from sajha.core.state import set_state_store
from sajha.core.state.memory import MemoryStateStore
from tests.ai.conftest import ToolBox, make_gateway

MULTI = "Compare the Sharpe ratio and Sortino ratio for a return of 12 with risk free rate 4 and volatility 15"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A registry whose learning settings the test sets, a routing store in tmp_path, a memory state store."""
    state = MemoryStateStore()
    set_state_store(state)
    store = L.RoutingStore(str(tmp_path / "routing"), reload_interval_s=0)
    L.set_store(store)
    L.set_bandit(None)
    monkeypatch.setattr(L, "_audit", lambda *a, **k: None)
    monkeypatch.setattr(L, "policy_gate", lambda pid, user: None)

    def make(**learning):
        reg = PlannerRegistry(settings=PlannerSettings(learning=PlannerLearningSettings(**learning)))
        set_registry(reg)
        L.set_bandit(None)
        return reg
    make()
    yield type("Env", (), {"make": staticmethod(make), "store": store, "state": state, "tmp": tmp_path})
    set_registry(None)
    L.set_store(None)
    L.set_bandit(None)
    set_state_store(None)


def ask(question=MULTI, tool="llm_t", gw=None, audit=None, **ctx):
    svc = IntelligenceService(gw or make_gateway(), ToolBox(),
                              settings=AskSettings(audit=audit is not None, planner="auto", planner_config={}),
                              audit=audit.append if audit is not None else None)
    events = list(svc.stream_ask(question, RequestContext(user_id="u", **ctx), planner_info={"tool": tool}))
    return [e for e in events if e["type"] == "planner_chosen"], events


def outcomes(tool, cls, planner, n, wins, cost=0.0, source="eval"):
    return [L.Outcome(tool, cls, planner, 1.0 if i < wins else 0.0, cost, 100.0, source) for i in range(n)]


# ── question classes ─────────────────────────────────────────────

@pytest.mark.parametrize("q,cls", [
    ("What is X? And what is Y?", "multi_part"),
    ("Fetch the rate and then convert it", "multi_part"),
    ("Compare Apple versus Microsoft", "compare"),
    ("What is the percentage change from 80 to 100?", "compute"),
    ("Who is the CEO of Apple?", "lookup"),
    ("Tell me a story about the markets in the long run of history", "general"),
])
def test_question_classes_are_fixed_rules(q, cls):
    assert L.question_class(q) == cls and L.question_class(q) == L.question_class(q)


# ── ranking ──────────────────────────────────────────────────────

def test_ranking_from_synthetic_outcomes_orders_by_score_and_needs_two_ranked_planners():
    xs = (outcomes("t", "compute", "calc_graph", 10, 9) + outcomes("t", "compute", "react", 10, 5)
          + outcomes("t", "compute", "reflect", 3, 3)                       # too few: listed, not ranked
          + outcomes("t", "lookup", "react", 10, 10))                       # one planner: no rule for lookup
    rules = L.rank(xs, min_samples=5)
    assert rules["t"]["compute"]["order"] == ["calc_graph", "react"]
    assert rules["t"]["compute"]["scores"]["reflect"]["ranked"] is False
    assert "lookup" not in rules["t"]
    assert rules["t"]["*"]["order"][0] == "calc_graph"                       # tool-wide, all classes
    assert rules["t"]["compute"]["scores"]["calc_graph"]["quality"] == 0.9


def test_the_cost_weight_can_change_the_order():
    xs = outcomes("t", "general", "reflect", 10, 10, cost=0.05) + outcomes("t", "general", "react", 10, 9, cost=0.001)
    assert L.rank(xs, min_samples=5)["t"]["general"]["order"] == ["reflect", "react"]
    assert L.rank(xs, min_samples=5, cost_weight=10)["t"]["general"]["order"] == ["react", "reflect"]


class Runs:
    def __init__(self, runs):
        self.runs = runs

    def list(self, kind, limit=200):
        return [dict(r, detail=None) for r in self.runs]

    def get(self, rid):
        return next(r for r in self.runs if r["id"] == rid)


def eval_run(rid, set_name, planner, rows, started_at=None):
    import time
    return {"id": rid, "status": "done", "started_at": started_at or time.time(),
            "summary": {"set": set_name, "planner": planner}, "detail": {"planner": planner, "questions": rows}}


def test_eval_outcomes_credit_the_planner_tested_and_the_choice_of_auto():
    from sajha.quality.evals import parse_set
    es = parse_set({"name": "s", "tool": "llm_t", "questions": [{"question": "q"}]})
    q = {"question": "What is the percentage change from 80 to 100?", "passed": True, "cost_usd": 0.01,
         "latency_ms": 50, "planner": "react"}
    held = dict(q, planner="auto>plan_execute",
                planner_choice={"chosen": "plan_execute", "class": "compute", "outcome": {"success": True}})
    lost = dict(held, planner_choice={"chosen": "react", "class": "compute", "outcome": {"success": False}})
    store = Runs([eval_run("a", "s", "react", [q]), eval_run("b", "s", "tool:llm_t", [held, lost, dict(q, planner="auto>x")]),
                  eval_run("old", "s", "react", [q], started_at=1.0)])
    got = L.eval_outcomes(since=100.0, store=store, sets={"s": es})
    assert [(o.tool, o.cls, o.planner, o.quality) for o in got] == [
        ("llm_t", "compute", "react", 1.0), ("llm_t", "compute", "plan_execute", 1.0),
        ("llm_t", "compute", "react", 0.0)]                                  # escalated first choice lost; old run skipped


def test_run_outcomes_read_planner_choice_from_audit_records_even_when_cut():
    rec = {"mode": "answer", "planner_choice": {"tool": "llm_t", "class": "compare", "chosen": "reflect",
                                                "outcome": {"success": True, "cost_usd": 0.02, "latency_ms": 900}},
           "planner_path": ["x"] * 2000}
    text = json.dumps(rec)[:4000]                                           # the audit cuts details at 4000
    pending = json.dumps({"planner_choice": {"tool": "t", "chosen": "react", "outcome": None}})
    got = L.run_outcomes(0, rows=[text, pending, "not json", '{"planner": "react"}'])
    assert len(got) == 1 and (got[0].tool, got[0].cls, got[0].planner, got[0].quality) == ("llm_t", "compare",
                                                                                            "reflect", 1.0)


# ── proposal -> approval -> effect -> rollback ───────────────────

def _audit_rows(tool, cls, good, bad, n=6):
    rows = []
    for planner, wins in ((good, n), (bad, 0)):
        for i in range(n):
            rows.append(json.dumps({"planner_choice": {"tool": tool, "class": cls, "chosen": planner,
                                                       "outcome": {"success": i < wins}}}))
    return rows


def test_proposal_approval_effect_and_rollback(env):
    env.make(min_samples=5)
    first, _ = ask()
    assert first[1]["planner"] == "plan_execute" and first[1]["by"].startswith("label")     # the model's choice
    doc = L.learn(created_by="cli", eval_store=Runs([]), sets={},
                  audit_rows=_audit_rows("llm_t", "compare", "react", "plan_execute"))
    assert doc["status"] == "proposed" and doc["rules"]["llm_t"]["compare"]["order"] == ["react", "plan_execute"]
    assert doc["diff"][0]["change"] == "added"
    again, _ = ask()
    assert again[1]["planner"] == "plan_execute"                            # a proposal changes nothing
    with pytest.raises(L.RoutingError) as e:
        L.approve(doc["id"], "0" * 64, "admin")
    assert e.value.status == 409                                             # not the hash the reviewer saw
    approved = L.approve(doc["id"], doc["hash"], type("U", (), {"user_id": "admin", "roles": ["admin"]})())
    assert approved["status"] == "approved" and approved["version"] == 1 and env.store.active()[0] == 1
    with pytest.raises(L.RoutingError):
        L.approve(doc["id"], doc["hash"], "admin")                           # only once
    chosen, events = ask()
    assert (chosen[1]["planner"], chosen[1]["by"]) == ("react", "learned")
    # the stream's reason is the audit's planner_choice.reason, not a repeat of "learned"
    assert chosen[1]["reason"] == "approved routing rules (compare)"
    assert ask(tool="other_tool")[0][1]["by"].startswith("label")            # rules are per tool
    L.activate(0, "admin", "test")                                           # rollback: no rules
    assert ask()[0][1]["by"].startswith("label")
    L.activate(1, "admin", "roll forward")
    assert ask()[0][1]["by"] == "learned"
    assert [h["action"] for h in env.store.history()][:3] == ["rollback", "off", "approve"]
    with pytest.raises(L.RoutingError):
        L.activate(9, "admin")


def test_rules_never_pick_a_planner_the_menu_does_not_allow(env):
    env.make()
    rules = {"llm_t": {"*": {"order": ["code_act", "rm_rf", "reflect", "react"], "scores": {}}}}
    doc = env.store.propose(rules, evidence={}, settings={})
    env.store.approve(doc["id"], doc["hash"], "admin")
    chosen, _ = ask()
    assert (chosen[1]["planner"], chosen[1]["by"]) == ("reflect", "learned")   # code_act is role-limited
    env.make(rules=False)                                                    # approved rules switched off
    assert ask()[0][1]["by"].startswith("label")


def test_a_rejected_or_empty_proposal_cannot_be_approved(env):
    env.make()
    empty = env.store.propose({}, evidence={}, settings={})
    with pytest.raises(L.RoutingError, match="no rules"):
        env.store.approve(empty["id"], empty["hash"], "admin")
    rules = {"t": {"*": {"order": ["react", "reflect"], "scores": {}}}}
    doc = env.store.propose(rules, evidence={}, settings={})
    env.store.reject(doc["id"], "admin", "not now")
    with pytest.raises(L.RoutingError, match="rejected"):
        env.store.approve(doc["id"], doc["hash"], "admin")
    with pytest.raises(L.RoutingError):
        env.store.proposal("../../etc/passwd")


def test_approval_goes_through_the_policy_engine(env, monkeypatch):
    env.make()
    doc = env.store.propose({"t": {"*": {"order": ["react", "reflect"], "scores": {}}}}, evidence={}, settings={})

    def refuse(pid, user):
        raise L.RoutingError("the policy engine refuses this approval", 403)
    monkeypatch.setattr(L, "policy_gate", refuse)
    with pytest.raises(L.RoutingError):
        L.approve(doc["id"], doc["hash"], "admin")
    assert env.store.proposal(doc["id"])["status"] == "proposed" and env.store.active()[0] == 0


# ── the outcome of a choice, in the audit record ─────────────────

def test_every_choice_and_its_outcome_go_into_the_audit_record(env):
    entries = []
    ask(audit=entries)
    pc = entries[0]["planner_choice"]
    assert pc["tool"] == "llm_t" and pc["class"] == "compare" and pc["chosen"] == "plan_execute"
    assert pc["by"] == "model" and "react" in pc["candidates"] and "code_act" not in pc["candidates"]
    assert pc["outcome"]["success"] is True and pc["outcome"]["escalated"] is False
    assert list(entries[0]).index("planner_choice") < list(entries[0]).index("planner_path")
    assert L.extract_choice(json.dumps(entries[0])) == pc


def test_finish_judges_a_choice_that_escalated_or_paused():
    choice = {"tool": "t", "class": "general", "candidates": ["react", "reflect"], "chosen": "react", "by": "model",
              "frame": 1}
    ok = [{"frame": 1, "planner": "react", "outcome": "answered", "stopped_by": None}]
    assert L.finish(choice, ok, "answer", 0, 10, record=False)["outcome"]["success"] is True
    esc = ok + [{"frame": 1, "planner": "reflect", "outcome": "answered", "stopped_by": None}]
    out = L.finish(choice, esc, "answer", 0, 10, record=False)["outcome"]
    assert out["success"] is False and out["escalated"] is True and out["reward"] == 0.0
    stopped = [{"frame": 1, "planner": "react", "outcome": "stopped", "stopped_by": "step_limit"}]
    assert L.finish(choice, stopped, "answer", 0, 10, record=False)["outcome"]["success"] is False
    assert L.finish(choice, ok, None, 0, 10, record=False)["outcome"]["success"] is False     # the service stopped it
    assert L.finish(choice, ok, "needs_input", 0, 10, record=False)["outcome"] is None


# ── the online bandit ────────────────────────────────────────────

def seed_arms(state, tool, cls, arms):
    for planner, (n, r) in arms.items():
        state.set(f"{L.K}arm:{tool}|{cls}|{planner}", {"n": n, "r": r})


def test_the_bandit_is_off_by_default_and_needs_opting_in(env):
    seed_arms(env.state, "llm_t", "compare", {"react": (20, 20), "plan_execute": (20, 0)})
    assert ask()[0][1]["by"].startswith("label")
    env.make(bandit=True, bandit_exploration=0.0)
    chosen, _ = ask()
    assert (chosen[1]["planner"], chosen[1]["by"]) == ("react", "bandit")    # exploits; no classify model call
    env.make(bandit=True, bandit_exploration=0.0, bandit_tools=["llm_other*"])
    assert ask()[0][1]["by"].startswith("label")                             # not one of the bandit's tools


def test_the_bandit_records_every_reward_and_its_kill_switch_stops_it(env):
    env.make(bandit=True, bandit_exploration=0.0)
    entries = []
    ask(audit=entries)
    pc = entries[0]["planner_choice"]
    assert pc["bandit"] is True and pc["outcome"]["reward"] == 1.0
    assert L.get_bandit().arm("llm_t", "compare", "plan_execute") == {"n": 1.0, "r": 1.0}
    L.get_bandit().kill("admin", "test")
    seed_arms(env.state, "llm_t", "compare", {"react": (20, 20), "plan_execute": (20, 0)})
    assert ask()[0][1]["by"].startswith("label")                             # stopped: the model chooses again
    assert L.get_bandit().arm("llm_t", "compare", "plan_execute")["n"] == 20  # and nothing is recorded
    L.get_bandit().resume("admin")
    assert ask()[0][1]["by"] == "bandit"


def test_the_bandit_never_picks_a_role_limited_or_eval_filtered_planner(env, monkeypatch):
    env.make(bandit=True, bandit_exploration=0.5, bandit_seed=1)
    seed_arms(env.state, "llm_t", "compare", {"code_act": (100, 100), "reflect": (100, 100), "react": (10, 1)})
    reg = PlannerRegistry(settings=PlannerSettings(learning=PlannerLearningSettings(
        bandit=True, bandit_exploration=0.5, bandit_seed=1)))
    monkeypatch.setattr(reg, "eval_filter", lambda tool, labels: [x for x in labels if x != "reflect"])
    set_registry(reg)
    picked = set()
    for _ in range(30):
        picked.add(ask()[0][1]["planner"])
    assert "code_act" not in picked and "reflect" not in picked and picked


def test_exploration_is_capped_and_reproducible_with_a_seed(env):
    st = PlannerLearningSettings(bandit=True, bandit_exploration=0.2, bandit_seed=7, bandit_min_samples=1)
    labels = ["react", "plan_execute", "reflect", "map_reduce"]

    def run(store):
        b = L.Bandit(st, store=store)
        seed = {"react": (50, 30), "plan_execute": (50, 28), "reflect": (50, 26), "map_reduce": (50, 27)}
        for p, (n, r) in seed.items():
            store.set(f"{L.K}arm:t|general|{p}", {"n": n, "r": r})
        return [b.choose("t", "general", labels, None) for _ in range(500)]
    a, b = run(MemoryStateStore()), run(MemoryStateStore())
    assert a == b                                                            # same seed, same choices
    explored = sum(1 for x in a if x[1] == "explore")
    assert 0 < explored <= 0.2 * len(a)
    assert all(x[0] in labels for x in a) and {x[0] for x in a if x[1] == "bandit"} == {"react"}


def test_ucb_tries_untried_arms_first_and_settings_are_bounded():
    st = PlannerLearningSettings(bandit=True, bandit_algorithm="ucb", bandit_exploration=0.5, bandit_seed=3)
    store = MemoryStateStore()
    for _ in range(40):
        store.window_add(f"{L.K}n:t", 3600)                                 # enough history to allow exploring
    b = L.Bandit(st, store=store)
    store.set(f"{L.K}arm:t|general|react", {"n": 10, "r": 9})
    picks = [b.choose("t", "general", ["react", "reflect"], None) for _ in range(20)]
    assert ("reflect", "explore", "ucb exploration") in picks
    with pytest.raises(Exception):
        PlannerLearningSettings(bandit_exploration=0.9)
    with pytest.raises(Exception):
        PlannerLearningSettings(bandit_algorithm="greedy")


def test_the_guard_stops_the_bandit_when_explored_choices_do_badly(env):
    st = PlannerLearningSettings(bandit=True, bandit_guard_min_runs=5, bandit_guard_min_success=0.5)
    b = L.Bandit(st, store=env.state)
    for _ in range(4):
        b.update("t", "general", "reflect", 0.0, explored=True)
    assert b.killed() is None
    b.update("t", "general", "reflect", 0.0, explored=True)
    assert b.killed()["by"] == "guard" and not b.active("t")


def test_the_cli_dry_run_and_status(env, monkeypatch, capsys):
    from sajha.ai.planners_engine import learn
    monkeypatch.setattr(learn, "_ensure_db", lambda: None)
    monkeypatch.setattr(L, "eval_outcomes", lambda *a, **k: outcomes("t", "general", "react", 6, 6)
                        + outcomes("t", "general", "reflect", 6, 2))
    monkeypatch.setattr(L, "run_outcomes", lambda *a, **k: [])
    assert learn.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "t [general]: react 1.00 (n=6), reflect 0.33 (n=6)" in out and not env.store.proposals()
    assert learn.main([]) == 0 and len(env.store.proposals()) == 1
    assert learn.main(["status"]) == 0 and "active version: none" in capsys.readouterr().out
    assert learn.main(["rollback", "3"]) == 2
