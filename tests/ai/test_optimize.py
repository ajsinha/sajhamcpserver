# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The optimize planner (docs/architecture/Quantitative Planners.md §3.6): the formulation's validation,
known optima of an LP, a MILP and a QP, infeasible and unbounded problems reported as such, the
feasibility check, the planner file end to end on the scripted mock model, and the path without
SciPy (a fresh interpreter with SciPy blocked: the planner is not loaded and an info notice says why)."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from sajha.ai.optimize.formulation import FormulationError, parse_formulation

ROOT = Path(__file__).resolve().parents[2]

try:
    import scipy.optimize  # noqa: F401
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False
needs_scipy = pytest.mark.skipif(not HAVE_SCIPY, reason="SciPy is not installed in this environment: the solver "
                                                        "tests need it (the not-installed path is tested below)")


def V(name, **kw):
    return {"name": name, **kw}


LP = {"sense": "max", "variables": [V("x"), V("y")], "objective": {"linear": {"x": 3, "y": 5}},
      "constraints": [{"name": "plant1", "terms": {"x": 1}, "op": "<=", "rhs": 4},
                      {"name": "plant2", "terms": {"y": 2}, "op": "<=", "rhs": 12},
                      {"name": "plant3", "terms": {"x": 3, "y": 2}, "op": "<=", "rhs": 18}]}
MILP = {"sense": "max", "variables": [V("x", integer=True), V("y", integer=True)],
        "objective": {"linear": {"x": 5, "y": 4}},
        "constraints": [{"terms": {"x": 6, "y": 4}, "op": "<=", "rhs": 24},
                        {"terms": {"x": 1, "y": 2}, "op": "<=", "rhs": 6}]}
QP = {"sense": "min", "variables": [V("a", upper=1), V("b", upper=1)],
      "objective": {"quadratic": [{"a": "a", "b": "a", "coef": 0.04}, {"a": "b", "b": "b", "coef": 0.09},
                                  {"a": "a", "b": "b", "coef": 0.012}]},
      "constraints": [{"name": "fully_invested", "terms": {"a": 1, "b": 1}, "op": "==", "rhs": 1}]}


# ── validation (no SciPy needed) ─────────────────────────────────

@pytest.mark.parametrize("bad, fragment", [
    ({**LP, "variables": [V("x"), V("x")]}, "declared twice"),
    ({**LP, "variables": [V("1x")]}, "identifier"),
    ({**LP, "objective": {"linear": {"z": 1}}}, '"z", which is not a variable'),
    ({**LP, "objective": {"linear": {"x": "3"}}}, "must be a number"),
    ({**LP, "objective": {"linear": {"x": True}}}, "must be a number"),
    ({**LP, "objective": {}}, "no terms"),
    ({**LP, "constraints": [{"terms": {"x": 1}, "op": "<", "rhs": 1}]}, "op must be one of"),
    ({**LP, "constraints": [{"terms": {"x": 1}, "op": "<=", "rhs": float("inf")}]}, "finite"),
    ({**LP, "variables": [V("x", lower=5, upper=1), V("y")]}, "above the upper bound"),
    ({**LP, "sense": "maximise"}, 'sense must be "min" or "max"'),
    ({**LP, "colour": "red"}, "unknown keys"),
    ([1, 2], "JSON object"),
])
def test_a_bad_formulation_is_refused_with_a_clear_error(bad, fragment):
    with pytest.raises(FormulationError) as e:
        parse_formulation(bad)
    assert any(fragment in m for m in e.value.errors), e.value.errors


def test_max_variables_is_enforced_and_capped():
    many = {"sense": "min", "variables": [V(f"v{i}") for i in range(6)], "objective": {"linear": {"v0": 1}},
            "constraints": []}
    with pytest.raises(FormulationError, match="at most 5"):
        parse_formulation(many, max_variables=5)
    assert len(parse_formulation(many, max_variables=6).variables) == 6
    with pytest.raises(FormulationError, match="at most 500"):
        parse_formulation({**many, "variables": [V(f"v{i}") for i in range(501)]}, max_variables=10_000)


def test_the_quantities_seam_resolves_every_number():
    seen = []

    def resolve(value, where):
        seen.append(where)
        return 2.0 if value == {"ref": "price"} else float(value)

    p = parse_formulation({**LP, "objective": {"linear": {"x": {"ref": "price"}, "y": 5}}}, resolve=resolve)
    assert p.linear["x"] == 2.0 and any("objective.linear" in w for w in seen)


# ── solving: known optima, infeasible, unbounded, the check ──────

@needs_scipy
def test_lp_known_optimum():
    from sajha.ai.optimize import solve
    r = solve(parse_formulation(LP))
    assert r["status"] == "optimal" and r["method"] == "linprog"
    assert r["objective"] == pytest.approx(36) and r["values"] == pytest.approx({"x": 2, "y": 6})
    assert r["check"]["ok"] and {c["name"] for c in r["check"]["constraints"] if c["binding"]} == {"plant2", "plant3"}


@needs_scipy
def test_milp_known_optimum_differs_from_its_relaxation():
    from sajha.ai.optimize import solve
    r = solve(parse_formulation(MILP))
    assert r["status"] == "optimal" and r["method"] == "milp"
    assert r["objective"] == pytest.approx(20) and r["values"] == {"x": 4.0, "y": 0.0}
    relaxed = solve(parse_formulation({**MILP, "variables": [V("x"), V("y")]}))
    assert relaxed["objective"] == pytest.approx(21)        # x = 3, y = 1.5


@needs_scipy
def test_qp_known_optimum_minimum_variance():
    from sajha.ai.optimize import solve
    r = solve(parse_formulation(QP))
    a = (0.18 - 0.012) / (0.08 + 0.18 - 2 * 0.012)            # d/da of the variance on a + b = 1
    assert r["status"] == "optimal" and r["method"] == "minimize"
    assert r["values"]["a"] == pytest.approx(a, abs=1e-6) and r["values"]["b"] == pytest.approx(1 - a, abs=1e-6)


@needs_scipy
@pytest.mark.parametrize("problem", [
    {"sense": "min", "variables": [V("x")], "objective": {"linear": {"x": 1}},
     "constraints": [{"terms": {"x": 1}, "op": "<=", "rhs": -1}]},
    {"sense": "min", "variables": [V("x", integer=True, upper=1)], "objective": {"linear": {"x": 1}},
     "constraints": [{"terms": {"x": 2}, "op": "==", "rhs": 1}]},
    {**QP, "constraints": QP["constraints"] + [{"terms": {"a": 1}, "op": ">=", "rhs": 2}]},
])
def test_infeasible_is_reported_as_such(problem):
    from sajha.ai.optimize import solve
    r = solve(parse_formulation(problem))
    assert r["status"] == "infeasible" and r["values"] is None and r["objective"] is None


@needs_scipy
@pytest.mark.parametrize("problem", [
    {"sense": "max", "variables": [V("x")], "objective": {"linear": {"x": 1}}, "constraints": []},
    {"sense": "max", "variables": [V("x", integer=True)], "objective": {"linear": {"x": 1}}, "constraints": []},
    {"sense": "min", "variables": [V("x", lower=None), V("y", lower=None)],
     "objective": {"linear": {"y": 1}, "quadratic": [{"a": "x", "b": "x", "coef": 1}]}, "constraints": []},
])
def test_unbounded_is_reported_as_such(problem):
    from sajha.ai.optimize import solve
    r = solve(parse_formulation(problem))
    assert r["status"] == "unbounded" and r["values"] is None


@needs_scipy
def test_a_non_convex_quadratic_is_refused_not_solved_locally():
    from sajha.ai.optimize import solve
    r = solve(parse_formulation({"sense": "min", "variables": [V("x", upper=3)],
                                 "objective": {"quadratic": [{"a": "x", "b": "x", "coef": -1}]}, "constraints": []}))
    assert r["status"] == "unsupported" and r["values"] is None


def test_the_feasibility_check_catches_a_bad_point():
    from sajha.ai.optimize import check_solution
    p = parse_formulation(MILP)
    assert check_solution(p, {"x": 4.0, "y": 0.0})["ok"]
    bad = check_solution(p, {"x": 3.5, "y": 1.0})
    assert not bad["ok"] and any("not an integer" in v for v in bad["violations"])
    assert any("does not hold" in v for v in check_solution(p, {"x": 5.0, "y": 0.0})["violations"])


@needs_scipy
def test_a_solver_point_that_fails_the_check_is_never_reported(monkeypatch):
    import scipy.optimize as so
    from sajha.ai.optimize import solve
    real = so.linprog

    def lying(c, **kw):
        r = real(c, **kw)
        if kw.get("A_ub") is not None and len(c) == 2 and r.status == 0:
            r.x = r.x + 1.0                                     # a point outside the feasible set
        return r
    monkeypatch.setattr(so, "linprog", lying)
    r = solve(parse_formulation(LP))
    assert r["status"] == "check_failed" and r["values"] is None and "feasibility check" in r["message"]


# ── the planner file on the scripted mock model ──────────────────

def _service(gw):
    from sajha.ai.intelligence import IntelligenceService
    from sajha.ai.llm.settings import AskSettings
    from tests.ai.conftest import ToolBox
    return IntelligenceService(gw, ToolBox(), settings=AskSettings(audit=False, planner="react",
                                                                   planner_config={}, synthesize=False))


def _scripted(steps):
    from tests.ai.conftest import make_gateway
    gw = make_gateway({"aliases": {a: ["mock/mock-scripted"] for a in ("default", "fast", "reasoning")},
                       "cache": {"enabled": False}})
    gw.providers["mock"].set_script(steps, mode="rules")
    return gw


@pytest.fixture
def registry():
    from sajha.ai.planners_engine import PlannerRegistry, set_registry
    reg = PlannerRegistry()
    set_registry(reg)
    yield reg
    set_registry(None)


ASK = "Two products earn 3 and 5 a unit; plant limits x <= 4, 2y <= 12, 3x + 2y <= 18. Best mix?"


@needs_scipy
def test_the_optimize_planner_solves_and_drafts_around_the_result(registry):
    gw = _scripted([{"stage": "act", "text": "I have what I need."},
                    {"stage": "optimize", "json": LP},
                    {"stage": "draft", "json": {"answer": "Make 2 of x and 6 of y for 36.", "citations": [],
                                                "caveats": []}}])
    events = list(_service(gw).stream_ask(ASK, _ctx(), planner="optimize"))
    r = events[-1]["result"]
    assert [p for p in r["planner_path"] if "/" not in p] == ["gather", "solve", "draft", "answer"]
    assert r["stopped_by"] == "answer" and "36" in r["answer"]
    opt = [e for e in events if e["type"] == "optimization"]
    assert opt and opt[0]["status"] == "optimal" and opt[0]["objective"] == pytest.approx(36)


@needs_scipy
def test_an_infeasible_problem_is_drafted_as_infeasible_with_no_solution(registry):
    infeasible = {**LP, "constraints": LP["constraints"] + [{"name": "min_x", "terms": {"x": 1}, "op": ">=",
                                                             "rhs": 10}]}
    gw = _scripted([{"stage": "act", "text": "ok"}, {"stage": "optimize", "json": infeasible},
                    {"stage": "draft", "json": {"answer": "No mix meets every limit.", "citations": [],
                                                "caveats": []}}])
    events = list(_service(gw).stream_ask(ASK, _ctx(), planner="optimize"))
    r = events[-1]["result"]
    assert [e["status"] for e in events if e["type"] == "optimization"] == ["infeasible"]
    assert any("infeasible" in c for c in r["caveats"])


@needs_scipy
def test_an_invalid_formulation_is_returned_to_the_model_then_fails(registry):
    bad = {**LP, "objective": {"linear": {"z": 1}}}
    gw = _scripted([{"stage": "act", "text": "ok"}, {"stage": "optimize", "json": bad}])
    r = _service(gw).ask(ASK, _ctx(), planner="optimize")
    assert [p for p in r.planner_path if "/" not in p] == ["gather", "solve", "fail"]
    assert r.stopped_by == "failed" and any("not a variable" in c for c in r.caveats)


def test_optimize_is_not_an_auto_default_candidate():
    import yaml
    auto = yaml.safe_load(open(ROOT / "config/planners/auto.yaml"))
    assert "optimize" not in auto["settings"]["candidates"] and "code_act" not in auto["settings"]["candidates"]


def _ctx(**kw):
    from sajha.ai.llm import RequestContext
    return RequestContext(user_id="u", **kw)


# ── without SciPy ────────────────────────────────────────────────

_BLOCK = textwrap.dedent("""
    import importlib.abc, sys

    class Block(importlib.abc.MetaPathFinder):
        def __init__(self, names): self.names = names
        def find_spec(self, name, path=None, target=None):
            if name.split('.')[0] in self.names:
                raise ImportError(f'blocked for the test: {name}')
            return None
    sys.meta_path.insert(0, Block({'scipy'}))
""")


def test_without_scipy_the_planner_is_not_loaded_and_an_info_notice_says_why():
    code = _BLOCK + textwrap.dedent("""
        from sajha import notices
        raised = []
        notices.raise_notice = lambda nid, **kw: raised.append((nid, kw))
        from sajha.ai.optimize import parse_formulation, available
        assert available()[0] is False and 'scipy' in available()[1].lower()
        parse_formulation({"sense": "min", "variables": [{"name": "x"}], "objective": {"linear": {"x": 1}},
                           "constraints": []})                 # validation still works
        from sajha.ai.planners_engine import get_registry
        reg = get_registry()
        reg.load()
        assert 'optimize' not in reg.names(), reg.names()
        assert 'optimize' in reg.unavailable and 'SciPy' in reg.unavailable['optimize']
        assert not reg.errors, reg.errors                     # not an error: an optional dependency
        assert 'react' in reg.names() and 'code_act' in reg.names()
        assert [n for n, kw in raised] == ['planners.unavailable:optimize'], raised
        assert raised[0][1]['severity'] == 'info' and raised[0][1]['source'] == 'planners'
        print('OK')
    """)
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-3000:]
