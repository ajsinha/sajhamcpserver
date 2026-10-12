# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Ask SAJHA over MCP, finished (docs/architecture/Intelligence Layer.md §6): destructive-tool confirmation
asked of the client (an MRTR input request on 2026-07-28, elicitation on the 2025-11-25 session stream, else
``needs_confirmation``); trimming the oldest turns on ContextTooLong before falling back to a larger model;
freshness and agreement in the confidence score."""

import asyncio
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

from sajha.ai.intelligence import (AskResult, AskStep, IntelligenceService, as_of_of, drop_oldest_turn, fingerprint,
                                   freshness_factor)
from sajha.ai.llm import RequestContext
from sajha.ai.llm.canonical import ChatMessage
from sajha.ai.llm.settings import AskSettings
from sajha.ai.llm_tools import LLMTool, LLMToolSettings, set_settings
from sajha.ai.llm_tools import confirmation as C
from sajha.ai.llm_tools.runtime import Runtime, set_runtime
from sajha.ai.memory import MemoryContext
from sajha.core.mcp_mrtr import InputRequired
from sajha.core.mcp_tool_context import ModernToolContext
from tests.ai.conftest import FakeTool, ToolBox, make_gateway

ROOT = Path(__file__).resolve().parent.parent.parent
ADMIN = RequestContext(user_id="", roles=["admin"], is_admin=True)
QUESTION = "Purge old records older than 30 days"
FP = fingerprint("records_purge", {"days": 30})
KEY = f"sajha_confirm_{FP}"


@pytest.fixture(autouse=True)
def fresh_runtime(tmp_path):
    from sajha.ai.llm_tools.config import SpoolSettings
    s = LLMToolSettings(spool=SpoolSettings(dir=str(tmp_path / "spool")))
    set_settings(s)
    set_runtime(Runtime(s))
    yield
    set_runtime(None)
    set_settings(None)


def purge_tool(name="records_purge"):
    return FakeTool(name, "Purge delete old records older than a number of days",
                    {"type": "object", "properties": {"days": {"type": "integer"}}, "required": ["days"]},
                    output={"purged": 12}, destructive=True)


def asker(name="t_ask"):
    box = ToolBox(with_calc=False)
    purge = box.add(purge_tool())
    cfg = {"name": name, "implementation": "sajha.ai.llm_tools.LLMTool", "description": "Ask over MCP.",
           "inputSchema": {"type": "object", "properties": {"question": {"type": "string"},
                                                            "confirm": {"type": "array", "items": {"type": "string"}}},
                           "required": ["question"]},
           "outputSchema": {"type": "object", "properties": {"answer": {"type": "string"},
                                                             "stopped_by": {"type": "string"}}},
           "llm": {"mode": "answer", "tools": {"allow": ["records_purge"]}}}
    t = LLMTool(cfg)
    gw = make_gateway()
    t.registry, t.gateway = box, gw
    t.service = IntelligenceService(gw, box, settings=AskSettings(), audit=lambda e: None)
    return t, purge


def modern_ctx(tool_name, responses=None, caps=None):
    ctx = ModernToolContext(client_capabilities={"elicitation": {}} if caps is None else caps,
                            input_responses=responses or {})
    ctx.tool_name = tool_name
    return ctx


def run_in(ctx, tool, args):
    token = ctx.activate()
    try:
        return tool.run(args, ctx=ADMIN, audit=False, remember=False)
    finally:
        ctx.deactivate(token)


def accept(confirm=True):
    return {"action": "accept", "content": {"confirm": confirm}}


# ── confirmation on 2026-07-28: MRTR ────────────────────────────────

def test_mrtr_asks_for_confirmation_then_runs_the_call():
    t, purge = asker()
    with pytest.raises(InputRequired) as ir:
        run_in(modern_ctx("t_ask"), t, {"question": QUESTION})
    assert purge.calls == []
    (key, req), = ir.value.requests.items()
    assert key == KEY and req["method"] == "elicitation/create"
    p = req["params"]
    assert p["mode"] == "form" and "records_purge" in p["message"] and '"days": 30' in p["message"]
    assert p["requestedSchema"]["properties"]["confirm"]["type"] == "boolean"
    assert p["requestedSchema"]["required"] == ["confirm"]
    info = run_in(modern_ctx("t_ask", {KEY: accept()}), t, {"question": QUESTION})
    assert purge.calls == [{"days": 30}]
    assert info.stopped_by == "answer" and "12" in info.result["answer"], info.result


def test_mrtr_decline_does_not_run_the_call():
    t, purge = asker()
    for answer in (accept(False), {"action": "decline"}, {"action": "cancel"}):
        info = run_in(modern_ctx("t_ask", {KEY: answer}), t, {"question": QUESTION})
        assert purge.calls == []
        step = [s for s in info.steps if s.name == "records_purge"][0]
        assert step.status == "refused" and "declined" in step.summary
        assert info.stopped_by != "needs_confirmation"


def test_without_a_channel_the_ask_stops_with_needs_confirmation():
    t, purge = asker()
    info = t.run({"question": QUESTION}, ctx=ADMIN, audit=False, remember=False)        # no MCP call at all
    assert info.stopped_by == "needs_confirmation" and info.result["pending"][0]["fingerprint"] == FP
    info = run_in(modern_ctx("t_ask", caps={}), t, {"question": QUESTION})                # no elicitation
    assert info.stopped_by == "needs_confirmation" and purge.calls == []
    info = run_in(modern_ctx("another_tool"), t, {"question": QUESTION})                 # not the call's tool
    assert info.stopped_by == "needs_confirmation" and purge.calls == []
    info = t.run({"question": QUESTION, "confirm": [FP]}, ctx=ADMIN, audit=False, remember=False)
    assert info.stopped_by == "answer" and purge.calls == [{"days": 30}]                # confirm still works


def test_url_only_elicitation_is_not_a_form_channel():
    t, purge = asker()
    info = run_in(modern_ctx("t_ask", caps={"elicitation": {"url": {}}}), t, {"question": QUESTION})
    assert info.stopped_by == "needs_confirmation" and purge.calls == []


# ── confirmation on 2025-11-25: elicitation on the session stream ────

class FakeCallContext:
    def __init__(self, answer=None, error=None):
        self.seen, self.answer, self.error = [], answer, error

    async def request(self, method, params, timeout=120.0):
        self.seen.append((method, params))
        if self.error:
            raise RuntimeError(self.error)
        return self.answer


@pytest.fixture
def loop():
    lp = asyncio.new_event_loop()
    th = threading.Thread(target=lp.run_forever, daemon=True)
    th.start()
    yield lp
    lp.call_soon_threadsafe(lp.stop)
    th.join(2)


def test_session_elicitation_confirms_and_runs(loop):
    t, purge = asker()
    call = FakeCallContext(accept())
    with C.bound(C.SessionConfirmer(call, loop, timeout_s=5), "t_ask"):
        info = t.run({"question": QUESTION}, ctx=ADMIN, audit=False, remember=False)
    assert call.seen[0][0] == "elicitation/create" and "records_purge" in call.seen[0][1]["message"]
    assert purge.calls == [{"days": 30}] and info.stopped_by == "answer"


def test_session_decline_and_failure(loop):
    t, purge = asker()
    with C.bound(C.SessionConfirmer(FakeCallContext({"action": "decline"}), loop, timeout_s=5), "t_ask"):
        info = t.run({"question": QUESTION}, ctx=ADMIN, audit=False, remember=False)
    assert purge.calls == [] and info.stopped_by != "needs_confirmation"
    with C.bound(C.SessionConfirmer(FakeCallContext(error="no UI"), loop, timeout_s=5), "t_ask"):
        info = t.run({"question": QUESTION}, ctx=ADMIN, audit=False, remember=False)
    assert purge.calls == [] and info.stopped_by == "needs_confirmation"      # falls back
    with C.bound(C.SessionConfirmer(FakeCallContext(accept()), loop, timeout_s=5), "other_tool"):
        info = t.run({"question": QUESTION}, ctx=ADMIN, audit=False, remember=False)
    assert purge.calls == [] and info.stopped_by == "needs_confirmation"      # bound to another tool


def test_policy_approval_by_the_caller_is_asked_through_the_client():
    """A policy rule that wants the caller's approval is the same question (ApprovalRequired, interactive)."""
    from sajha.policy import context as pctx
    from sajha.policy.errors import ApprovalRequired
    box = ToolBox(with_calc=False)
    seen = []

    class Gated(FakeTool):
        def execute_with_tracking(self, arguments):
            seen.append(pctx.confirmed())
            if not pctx.confirmed():
                raise ApprovalRequired("over the limit", interactive=True)
            return {"archived": 7}

    box.add(Gated("records_archive", "Archive old records older than a number of days",
                  {"type": "object", "properties": {"days": {"type": "integer"}}}))

    class Answer(C.ClientConfirmer):
        kind = "test"

        def __init__(self, value):
            self.value, self.asked = value, []

        def decide(self, pending):
            self.asked.append(pending)
            return self.value

    yes = Answer(True)
    svc = IntelligenceService(make_gateway(), box, settings=AskSettings(), audit=lambda e: None)
    r = svc.ask("Archive old records older than 30 days", RequestContext(user_id="u"), confirmer=yes)
    assert yes.asked and yes.asked[0]["reason"].startswith("policy:")
    assert r.stopped_by == "answer" and seen == [False, True]
    no = Answer(False)
    r = svc.ask("Archive old records older than 30 days", RequestContext(user_id="u"), confirmer=no)
    assert r.steps[0].status == "refused" and "declined" in r.steps[0].summary
    r = svc.ask("Archive old records older than 30 days", RequestContext(user_id="u"))
    assert r.stopped_by == "needs_confirmation"


# ── confirmation end to end over /mcp ───────────────────────────────

@pytest.fixture(scope="module")
def app():
    from fastapi.testclient import TestClient
    sys.path.insert(0, str(ROOT))
    os.chdir(str(ROOT))
    from sajha.app import create_app
    with TestClient(create_app()) as c:
        from sajha.app import tools_registry
        from sajha.auth import apikeys as svc
        from sajha.auth.password import hash_password
        from sajha.db.dao import RoleDAO, UserDAO
        from sajha.db.engine import get_db_session
        from sajha.db.models import User
        purge = purge_tool("e2e_records_purge")
        tools_registry.register_tool(purge)
        t, _ = asker("e2e_ask")
        t.config["llm"]["tools"]["allow"] = ["e2e_records_purge"]
        t = LLMTool(t.config)
        gw = make_gateway()
        t.registry, t.gateway = tools_registry, gw
        t.service = IntelligenceService(gw, tools_registry, settings=AskSettings(), audit=lambda e: None)
        tools_registry.register_tool(t)
        uid = f"ask_{uuid.uuid4().hex[:8]}"
        db = get_db_session()
        try:
            user = User(user_id=uid, user_name=uid, email="", password_hash=hash_password("Ask-Pass-12345"),
                        enabled=True)
            user.roles.append(RoleDAO(db).get_or_create("admin"))
            UserDAO(db).create(user)
            _, raw = svc.create_key(db, name="ask-" + uuid.uuid4().hex[:6], created_by="test", owner=user)
        finally:
            db.close()
        yield c, raw, purge
        tools_registry.unregister_tool("e2e_ask")
        tools_registry.unregister_tool("e2e_records_purge")


def test_2026_07_28_round_trip(app):
    c, key, purge = app
    purge.calls.clear()
    meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {"elicitation": {}},
            "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1"}}
    hdrs = {"MCP-Protocol-Version": "2026-07-28", "Mcp-Method": "tools/call", "Mcp-Name": "e2e_ask",
            "Accept": "application/json, text/event-stream", "X-API-Key": key}
    params = {"name": "e2e_ask", "arguments": {"question": QUESTION}, "_meta": meta}
    r = c.post("/mcp", headers=hdrs, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    res = r.json()["result"]
    assert res["resultType"] == "input_required", res
    (k, req), = res["inputRequests"].items()
    assert k == f"sajha_confirm_{fingerprint('e2e_records_purge', {'days': 30})}"
    assert req["method"] == "elicitation/create" and purge.calls == []
    params2 = {**params, "inputResponses": {k: accept()}, "requestState": res["requestState"]}
    r = c.post("/mcp", headers=hdrs, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": params2})
    res = r.json()["result"]
    assert res.get("isError") is not True and res["structuredContent"]["stopped_by"] == "answer", res
    assert purge.calls == [{"days": 30}]
    # a client without elicitation: the result is needs_confirmation, as before
    meta_none = {**meta, "io.modelcontextprotocol/clientCapabilities": {}}
    r = c.post("/mcp", headers=hdrs, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                           "params": {**params, "_meta": meta_none}})
    res = r.json()["result"]
    assert res["structuredContent"]["stopped_by"] == "needs_confirmation", res
    assert purge.calls == [{"days": 30}]


def test_2025_11_25_round_trip_over_the_session_stream(app):
    """Over a real socket (the TestClient buffers a streamed response): uvicorn on a free port."""
    import socket
    import httpx
    import uvicorn
    c, key, purge = app
    purge.calls.clear()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(c.app, host="127.0.0.1", port=port, lifespan="off", log_level="error"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        base = f"http://127.0.0.1:{port}/mcp"
        with httpx.Client(timeout=20) as hc:
            init = hc.post(base, headers={"X-API-Key": key}, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-11-25", "capabilities": {"elicitation": {}},
                    "clientInfo": {"name": "pytest", "version": "1"}}})
            h = {"X-API-Key": key, "Mcp-Session-Id": init.headers["mcp-session-id"],
                 "MCP-Protocol-Version": "2025-11-25"}
            hc.post(base, headers=h, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            final, asked = None, []
            with httpx.Client(timeout=20) as other, hc.stream(
                    "POST", base, headers={**h, "Accept": "application/json, text/event-stream"}, json={
                        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
                        "params": {"name": "e2e_ask", "arguments": {"question": QUESTION}}}) as r:
                for line in r.iter_lines():
                    if not line.startswith("data:") or not line[5:].strip():
                        continue
                    msg = json.loads(line[5:])
                    if msg.get("method") == "elicitation/create":
                        asked.append(msg["params"])
                        ack = other.post(base, headers=h, json={"jsonrpc": "2.0", "id": msg["id"],
                                                                "result": accept()})
                        assert ack.status_code == 202
                    elif msg.get("id") == 7:
                        final = msg
                        break
        assert asked and "e2e_records_purge" in asked[0]["message"]
        assert final["result"]["structuredContent"]["stopped_by"] == "answer", final
        assert purge.calls == [{"days": 30}]
    finally:
        server.should_exit = True
        th.join(5)


# ── trimming on ContextTooLong ──────────────────────────────────────

def turns(n):
    out = []
    for i in range(1, n + 1):
        out += [ChatMessage.user(f"old question {i}"), ChatMessage.assistant(f"old answer {i}")]
    return out


def recording(gw):
    sent = []
    real = gw.chat_completions_create

    def create(req=None, /, **kw):
        sent.append(req)
        return real(req, **kw)
    gw.chat_completions_create = create
    return sent


def test_drop_oldest_turn_keeps_system_question_and_tool_results():
    hist = turns(2)
    msgs = [ChatMessage.system("sys")] + hist + [ChatMessage.user("now?"), ChatMessage.assistant("…"),
                                                 ChatMessage.tool("c1", "{}", tool_name="x")]
    one = drop_oldest_turn(msgs, hist)
    assert [m.text for m in one][:4] == ["sys", "old question 2", "old answer 2", "now?"]
    two = drop_oldest_turn(one, hist[2:])
    assert [m.role for m in two] == ["system", "user", "assistant", "tool"] and two[1].text == "now?"
    assert drop_oldest_turn(two, []) is None and drop_oldest_turn(two, hist) is None
    # the same question asked again is never taken for the earlier turn
    again = [ChatMessage.user("now?"), ChatMessage.assistant("before"), ChatMessage.user("now?")]
    assert drop_oldest_turn(again, again[:2]) == [again[2]]


def test_context_too_long_trims_the_oldest_turn_and_retries_the_same_model():
    gw = make_gateway({"aliases": {"default": ["mock/mock-scripted", "mock/mock-echo"]}, "cache": {"enabled": False}})
    gw.providers["mock"].set_script([{"error": "context_too_long"}, {"text": "Fits now."}])
    sent = recording(gw)
    svc = IntelligenceService(gw, ToolBox(with_calc=False), settings=AskSettings(), audit=lambda e: None)
    mc = MemoryContext("c1", False, history=turns(2), standalone="And now?", turn=3)
    events = list(svc.stream_ask("And now?", RequestContext(user_id="u"), memory_context=mc, _objects=True))
    res = events[-1]["result"]
    assert res.answer == "Fits now." and res.models == ["mock/mock-scripted"]           # no fallback
    assert res.context_trims == [{"step": 1, "model": "mock/mock-scripted", "dropped_messages": 2,
                                  "dropped_turns": 1, "turns_left": 1}]
    texts = [[m.text for m in r.messages] for r in sent]
    assert "old question 1" in texts[0] and "old question 1" not in texts[1] and "old question 2" in texts[1]
    assert all(r.model == "mock/mock-scripted" for r in sent)                          # pinned candidate
    trimmed = [e for e in events if e["type"] == "context_trimmed"]
    assert trimmed and trimmed[0]["dropped_turns"] == 1
    assert res.to_dict()["context_trims"] == res.context_trims


def test_with_nothing_left_to_trim_the_call_falls_back_to_the_next_model():
    gw = make_gateway({"aliases": {"default": ["mock/mock-scripted", "mock/mock-echo"]}, "cache": {"enabled": False}})
    gw.providers["mock"].set_script([{"error": "context_too_long"}], loop=True)
    audit = []
    svc = IntelligenceService(gw, ToolBox(with_calc=False), settings=AskSettings(), audit=audit.append)
    mc = MemoryContext("c1", False, history=turns(1), standalone="And now?", turn=2)
    res = svc.ask("And now?", RequestContext(user_id="u"), memory_context=mc)
    assert res.models == ["mock/mock-echo"] and res.stopped_by == "answer"              # the larger model
    assert len(res.context_trims) == 1 and res.context_trims[0]["model"] == "mock/mock-scripted"
    assert audit[0]["context_trims"] == res.context_trims


def test_without_history_the_gateway_falls_back_as_before():
    gw = make_gateway({"aliases": {"default": ["mock/mock-scripted", "mock/mock-echo"]}, "cache": {"enabled": False}})
    gw.providers["mock"].set_script([{"error": "context_too_long"}], loop=True)
    sent = recording(gw)
    svc = IntelligenceService(gw, ToolBox(with_calc=False), settings=AskSettings(), audit=lambda e: None)
    res = svc.ask("Hello there", RequestContext(user_id="u"))
    assert res.models == ["mock/mock-echo"] and res.context_trims == []
    assert sent[0].model == "default"                                                   # not pinned


# ── freshness and agreement in the confidence score ─────────────────

def _svc():
    return IntelligenceService(make_gateway(), ToolBox(with_calc=False), settings=AskSettings(), audit=lambda e: None)


def _iso_days_ago(days):
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_as_of_is_read_from_the_result():
    assert as_of_of({"price": 1, "as_of": "2026-01-02"}) is not None
    nested = {"data": [{"v": 1, "last_updated": "2026-01-02T00:00:00Z"}, {"v": 2, "as_of": "2026-03-01"}]}
    from datetime import datetime, timezone
    assert as_of_of(nested) == datetime(2026, 3, 1, tzinfo=timezone.utc).timestamp()     # the newest
    assert as_of_of({"as_of": 1767312000}) == 1767312000.0 and as_of_of({"as_of": 1767312000000}) == 1767312000.0
    assert as_of_of({"date": "2026-01-02", "note": "as_of"}) is None and as_of_of({"as_of": "soon"}) is None
    assert [freshness_factor(d) for d in (0.5, 3, 20, 100, 800)] == [1.0, 0.95, 0.9, 0.8, 0.7]


def test_stale_results_lower_the_confidence():
    def res_with(as_of, question="price of X?"):
        st = AskStep("c1", "calc_quote", {}, True, "ok", "", 1, 1.0, "fp", None, as_of)
        return AskResult(question=question, answer="It is 5.", steps=[st], citations=["c1"])
    svc = _svc()
    fresh, _ = svc._confidence(res_with(_iso_days_ago(0.1)))
    assert fresh == pytest.approx(1.0)
    stale, basis = svc._confidence(res_with(_iso_days_ago(100)))
    assert stale == pytest.approx(0.8) and any(b.get("step") == "freshness:calc_quote" for b in basis)
    old, _ = svc._confidence(res_with(_iso_days_ago(1000)))
    assert old == pytest.approx(0.7)
    asked = res_with("2020-01-02T00:00:00Z", question="What was X on 2020-01-02?")
    assert svc._confidence(asked, question=asked.question)[0] == pytest.approx(1.0)       # the date was asked for
    none, _ = svc._confidence(res_with(None))
    assert none == pytest.approx(1.0)                                                    # no date, no penalty


def test_agreement_across_sources_raises_the_confidence():
    s1 = AskStep("a", "web_quote_a", {}, True, "ok", "", 1, 0.8, "f1")
    s2 = AskStep("b", "web_quote_b", {}, True, "ok", "", 1, 0.8, "f2")
    results = [{"id": "a", "ok": True, "data": {"price": 190.1}, "preview": ""},
               {"id": "b", "ok": True, "data": {"last": 190.10, "volume": 5000}, "preview": ""}]
    res = AskResult(question="price of X?", answer="X trades at 190.10.", steps=[s1, s2], citations=["a", "b"])
    value, basis = _svc()._confidence(res, results)
    assert value == pytest.approx(0.64 + 0.36 * 0.25)
    agree = [b for b in basis if b.get("rule") == "agreement"][0]
    assert agree["corroboration"] == 1.0 and agree["corroborated"] == ["190.10"]
    # one source only, or figures each source alone backs: no bonus
    single = AskResult(question="q", answer="X trades at 190.10.", steps=[s1], citations=["a"])
    assert _svc()._confidence(single, results[:1])[0] == pytest.approx(0.8)
    apart = AskResult(question="q", answer="X trades at 190.10 on volume 5000.", steps=[s1, s2], citations=["a", "b"])
    value, _ = _svc()._confidence(apart, results)
    assert value == pytest.approx(0.64 + 0.36 * 0.25 * 0.5)


def test_reconciliation_breaks_lower_and_matches_raise_the_confidence():
    s1 = AskStep("a", "web_a", {}, True, "ok", "", 1, 0.8, "f1")
    s2 = AskStep("b", "web_b", {}, True, "ok", "", 1, 0.8, "f2")
    broke = AskResult(question="q", answer="They differ.", steps=[s1, s2], citations=["a", "b"],
                      reconciliations=[{"figures": [{"status": "compared"}], "breaks": [{"x": 1}]}])
    assert _svc()._confidence(broke)[0] == pytest.approx(0.64 * 0.8)
    match = AskResult(question="q", answer="They agree.", steps=[s1, s2], citations=["a", "b"],
                      reconciliations=[{"figures": [{"status": "compared"}], "breaks": []}])
    assert _svc()._confidence(match)[0] == pytest.approx(0.64 + 0.36 * 0.25)


def test_an_ask_records_the_as_of_of_each_result():
    box = ToolBox(with_calc=False)
    box.add(FakeTool("quote_fetch", "Fetch the stock quote price for a ticker symbol",
                     {"type": "object", "properties": {"symbol": {"type": "string"}}},
                     output={"symbol": "AAPL", "price": 190.1, "as_of": _iso_days_ago(400)}))
    svc = IntelligenceService(make_gateway(), box, settings=AskSettings(), audit=lambda e: None)
    r = svc.ask("Fetch the stock quote price for AAPL", RequestContext(user_id="u"))
    assert r.steps[0].as_of and r.steps[0].as_of.endswith("Z")
    plain = IntelligenceService(make_gateway(), box, settings=AskSettings(), audit=lambda e: None)
    box.tools["quote_fetch"].output = {"symbol": "AAPL", "price": 190.1}
    assert plain.ask("Fetch the stock quote price for AAPL", RequestContext(user_id="u")).confidence > r.confidence
