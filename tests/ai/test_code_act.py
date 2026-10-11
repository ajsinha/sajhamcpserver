# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""The code_act planner (docs/architecture/Quantitative Planners.md §3.5): role-limited by
ai.quant.code_act.roles (a caller without the role is never offered it, auto never picks it, a direct
run is refused); output that is not quantities as JSON is rejected and returned to the model; the
code runs in the sandbox with the network off; every run is in the run record and the audit."""

import json
import socket
import sys
import threading

import pytest

from sajha.ai.code_act.sandboxed import CodeOutputError, parse_output, policy, run_code
from sajha.ai.llm import RequestContext
from sajha.ai.planners_engine import PlannerRegistry, set_registry
from sajha.ai.quant.settings import QuantCodeActSettings, QuantSettings, set_quant_settings
from tests.ai.conftest import ToolBox, make_gateway

QUESTION = "What is 6 times 7 in US dollars?"
GOOD = ("import json, sys\nd = json.load(sys.stdin)\n"
        "print(json.dumps({'quantities': {'product': {'value': 6 * 7, 'unit': 'USD'}}}))\n")
linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="network confinement is Linux-only "
                                                                               "(docs/architecture/Sandbox.md §4)")


@pytest.fixture(autouse=True)
def registry():
    reg = PlannerRegistry()
    set_registry(reg)
    yield reg
    set_registry(None)
    set_quant_settings(None)


def allow(*roles):
    set_quant_settings(QuantSettings(code_act=QuantCodeActSettings(roles=list(roles))))


@pytest.fixture
def audits(monkeypatch):
    from sajha.core.audit import AuditLogger
    got = []
    monkeypatch.setattr(AuditLogger, "log", lambda self, action, **kw: got.append((action, kw)))
    return got


def ctx(*roles):
    return RequestContext(user_id="u", roles=list(roles))


def service(gw):
    from sajha.ai.intelligence import IntelligenceService
    from sajha.ai.llm.settings import AskSettings
    return IntelligenceService(gw, ToolBox(), settings=AskSettings(audit=False, planner="react", planner_config={},
                                                                   synthesize=False))


def scripted(steps, mode="ordered"):
    gw = make_gateway({"aliases": {a: ["mock/mock-scripted"] for a in ("default", "fast", "reasoning")},
                       "cache": {"enabled": False}})
    gw.providers["mock"].set_script(steps, mode=mode)
    return gw


DRAFT = {"json": {"answer": "It is 42 USD.", "citations": [], "caveats": []}}


# ── who may run it ───────────────────────────────────────────────

def test_the_default_is_no_role_so_nobody_runs_it(registry):
    assert registry.refusal("code_act", ctx("admin")) is not None
    r = service(scripted([{"text": "ok"}])).ask(QUESTION, RequestContext(user_id="a", roles=["admin"], is_admin=True),
                                                planner="code_act")
    assert r.stopped_by == "refused" and r.planner_path == []


def test_a_role_without_permission_never_sees_it(registry, monkeypatch, audits):
    allow("quant")
    assert registry.refusal("code_act", ctx("quant")) is None
    assert registry.refusal("code_act", ctx("user")) is not None
    # not listed for the caller
    names = {d["name"] for d in registry.describe(ctx=ctx("user"), hide_refused=True)}
    assert "code_act" not in names and "react" in names
    assert "code_act" in {d["name"] for d in registry.describe(ctx=ctx("quant"), hide_refused=True)}
    listed = {d["name"]: d for d in registry.describe(ctx=ctx("user"))}
    assert listed["code_act"]["roles"] == ["quant"] and listed["code_act"]["permitted"] is False
    # a direct run is refused before any model call or code
    gw = scripted([{"json": {"code": GOOD}}])
    r = service(gw).ask(QUESTION, ctx("user"), planner="code_act")
    assert r.stopped_by == "refused" and not r.code_runs and not audits
    # auto never picks it, even when an overlay adds it and the question names it
    overlay = {"auto": {"settings": {"candidates": ["react", "code_act"], "default": "react"}}}
    plan_q = "Use code_act to compute 6 times 7"
    gw = make_gateway({"aliases": {a: ["mock/mock-planner"] for a in ("default", "fast", "reasoning")},
                       "cache": {"enabled": False}})
    events = list(service(gw).stream_ask(plan_q, ctx("user"), planner={"use": "auto", **overlay["auto"]}))
    chosen = [e["planner"] for e in events if e["type"] == "planner_chosen"]
    assert "code_act" not in chosen and "react" in chosen
    # the same question from a caller with the role: the menu offers it (so the check above is real)
    gw = make_gateway({"aliases": {a: ["mock/mock-planner"] for a in ("default", "fast", "reasoning")},
                       "cache": {"enabled": False}})
    events = list(service(gw).stream_ask(plan_q, ctx("quant"), planner={"use": "auto", **overlay["auto"]}))
    assert "code_act" in [e["planner"] for e in events if e["type"] == "planner_chosen"]


def test_a_sub_planner_stage_refuses_it_for_the_wrong_role(registry):
    allow("quant")
    doc = {"name": "wrap", "version": "1.0.0", "description": "d", "use_when": "u", "start": "go",
           "stages": {"go": {"type": "planner", "planner": "code_act", "outcomes": {"*": {"next": "answer"}}},
                      "answer": {"type": "answer"}}}
    pdef = registry.inline(doc, {})
    assert registry.refusal(pdef, ctx("user")) is not None and registry.refusal(pdef, ctx("quant")) is None


def test_the_planner_list_route_hides_it_from_callers_without_the_role(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sajha.auth import AuthContext, require_auth
    from sajha.routes.ai_routes import router
    allow("quant")
    app = FastAPI()
    app.include_router(router)
    for roles, admin, seen in ((["user"], False, False), (["quant"], False, True), (["admin"], True, True)):
        who = AuthContext(authenticated=True, user_id="x", roles=roles, is_admin=admin)
        app.dependency_overrides[require_auth] = lambda who=who: who
        body = TestClient(app).get("/api/ai/planners").json()
        names = {p["name"]: p for p in body["planners"]}
        assert ("code_act" in names) is seen, roles
        if admin:
            assert names["code_act"]["permitted"] is False


# ── output, sandbox, audit ───────────────────────────────────────

@pytest.mark.parametrize("stdout, fragment", [
    ("", "printed nothing"),
    ("hello", "not one JSON object"),
    ("42", "JSON object of quantities"),
    ('{"x": 42}', "has no unit"),
    ('{"x": {"value": 1, "unit": ""}}', "non-empty string"),
    ('{"x": {"value": 1, "unit": "USD", "colour": 1}}', "unknown keys"),
    ('{"1x": {"value": 1, "unit": "USD"}}', "identifier"),
    ('{"quantities": {}}', "names no quantities"),
])
def test_output_that_is_not_quantities_is_rejected(stdout, fragment):
    with pytest.raises(CodeOutputError, match=fragment):
        parse_output(stdout)
    assert parse_output('{"quantities": {"x": {"value": [1, 2], "unit": "USD mn"}}}')["x"]["unit"] == "USD mn"


def test_bad_output_goes_back_to_the_model_then_good_output_is_used(registry, audits):
    allow("quant")
    bad = "print('the answer is 42')\n"
    gw = scripted([{"text": "I have what I need."}, {"json": {"code": bad}}, {"json": {"code": GOOD}}, DRAFT])
    events = list(service(gw).stream_ask(QUESTION, ctx("quant"), planner="code_act"))
    r = events[-1]["result"]
    assert [p for p in r["planner_path"] if "/" not in p] == ["gather", "compute", "draft", "answer"]
    runs = r["code_runs"]
    assert [c["ok"] for c in runs] == [False, True]
    assert "not one JSON object" in runs[0]["error"] and runs[1]["quantities"] == ["product"]
    assert runs[0]["input_digest"] == runs[1]["input_digest"] and runs[1]["input_digest"].startswith("sha256:")
    assert json.loads(runs[1]["output"])["quantities"]["product"]["value"] == 42
    assert [e["ok"] for e in events if e["type"] == "code_run"] == [False, True]
    # the error was returned to the model
    sent = gw.providers["mock"].script("default")
    assert sent.cursor == 4
    # audited: one ai_code_act event per run, with the code, input digest and output
    assert [a for a, _kw in audits] == ["ai_code_act", "ai_code_act"]
    detail = json.loads(audits[1][1]["details"])
    assert detail["code"] == GOOD and detail["input_digest"] == runs[1]["input_digest"] and '"product"' in detail["output"]
    assert audits[1][1]["user_id"] == "u"


def test_a_unit_the_workspace_does_not_know_is_refused(registry, audits):
    allow("quant")
    odd = "import json\nprint(json.dumps({'x': {'value': 1, 'unit': 'furlongs per fortnight'}}))\n"
    gw = scripted([{"text": "ok"}, {"json": {"code": odd}}, {"json": {"code": odd}}])
    r = service(gw).ask(QUESTION, ctx("quant"), planner="code_act")
    assert r.stopped_by == "failed" and all("refused" in c["error"] for c in r.code_runs)


def test_the_policy_is_the_sandbox_default_with_the_network_off(monkeypatch):
    from sajha.sandbox import settings as sbs
    real = sbs.load_settings

    def allowlisted():
        s = real()
        s.defaults = dict(s.defaults, network="allowlist", allow_hosts=["example.com:443"])
        return s
    monkeypatch.setattr("sajha.sandbox.policy.load_settings", allowlisted)
    p = policy()
    assert p.network == "none" and p.allow_hosts == [] and p.backend is None


@linux_only
def test_the_network_is_off_inside_the_sandbox():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    hits = []
    threading.Thread(target=lambda: hits.append(srv.accept()), daemon=True).start()
    code = ("import json, socket, sys\n"
            "try:\n"
            f"    socket.create_connection(('127.0.0.1', {port}), timeout=3); ok = 1\n"
            "except Exception as e:\n"
            "    print(repr(e), file=sys.stderr); ok = 0\n"
            "print(json.dumps({'reached': {'value': ok, 'unit': 'count'}}))\n")
    try:
        run = run_code(code, "{}")
    finally:
        srv.close()
    assert run.ok, run.error
    assert run.quantities["reached"]["value"] == 0 and not hits


def test_the_code_reads_its_input_on_stdin_and_cannot_read_server_files():
    code = ("import json, sys\nd = json.load(sys.stdin)\n"
            "try:\n    open('config/application.yml').read(); leak = 1\nexcept Exception:\n    leak = 0\n"
            "print(json.dumps({'a': {'value': d['quantities']['q']['value'] * 2, 'unit': 'USD'},"
            " 'leak': {'value': leak, 'unit': 'count'}}))\n")
    payload = json.dumps({"question": "q", "quantities": {"q": {"value": 21, "unit": "USD"}}, "results": []})
    run = run_code(code, payload)
    assert run.ok, run.error
    assert run.quantities["a"]["value"] == 42 and run.quantities["leak"]["value"] == 0
