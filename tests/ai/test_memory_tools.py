# Copyright All rights Reserved 2025-2030, Ashutosh Sinha, Email: ajsinha@gmail.com
"""Conversation memory for LLM tools (sajha/ai/memory.py; docs/architecture/LLM Tools.md §10): the handle
(create, continue, "conversation not found" for everything else), per-tool scoping, expiry, turn folding,
question clipping, reading only the window, client history, no storage for anonymous callers, the
scheduled purge that runs once across workers, and its metrics. Mock provider; one SQLite file per test."""

import time

import pytest
from sqlalchemy import create_engine, update

from sajha.ai.llm import RequestContext
from sajha.ai.llm.settings import MemorySettings
from sajha.ai.memory import (ConversationMemory, ConversationNotFound, ConversationStore, PurgeScheduler,
                             ToolMemorySettings, ai_conversations, client_history, tool_memory_settings)
from sajha.core.state.memory import MemoryStateStore
from tests.ai.conftest import make_gateway

ALICE = RequestContext(user_id="alice")
TOOL = "fx_assistant"


@pytest.fixture
def store(tmp_path):
    return ConversationStore(create_engine(f"sqlite:///{tmp_path / 'm.db'}"))


def memory(store, tool=None, **mem):
    return ConversationMemory(make_gateway(), MemorySettings(**mem), store, tool or ToolMemorySettings())


def turn(mem, cid, q="What is the rate?", ctx=ALICE, tool=TOOL, **kw):
    mc = mem.open(cid, q, ctx, tool_name=tool, **kw)
    seq = mem.record(mc, ctx, q, answer=f"answer to {q}", tools=["fx_rate"], stopped_by="answer", confidence=0.9)
    return mc, seq


def test_the_handle_creates_continues_and_never_says_forbidden(store):
    mem = memory(store)
    mc, seq = turn(mem, None)
    assert mc.is_new and mc.stored and seq == 1
    cid = mc.conversation_id
    mc2, seq2 = turn(mem, cid, "And yesterday?")
    assert not mc2.is_new and mc2.turn == 2 and seq2 == 2 and mc2.history[0].text == "What is the rate?"
    for bad_cid, ctx, tool in [("0" * 36, ALICE, TOOL),                       # unknown
                               ("not an id!", ALICE, TOOL),                    # malformed
                               (cid, RequestContext(user_id="mallory"), TOOL),  # another user's
                               (cid, ALICE, "other_tool")]:                    # another tool's
        with pytest.raises(ConversationNotFound, match="conversation not found"):
            mem.open(bad_cid, "x", ctx, tool_name=tool)
    with pytest.raises(ConversationNotFound):                                  # the Ask SAJHA page's scope
        mem.context(cid, "x", ALICE)
    assert store.get(cid, "alice", None) is None and store.get(cid, "alice", TOOL)["tool_name"] == TOOL
    with store.engine.begin() as c:                                            # expired
        c.execute(update(ai_conversations).values(expires_ts=time.time() - 1))
    with pytest.raises(ConversationNotFound, match="conversation not found"):
        mem.open(cid, "x", ALICE, tool_name=TOOL)


def test_ask_page_conversations_are_not_continued_by_a_tool(store):
    mem = memory(store)
    mc = mem.context("new", "What is the rate?", ALICE)
    mem.record(mc, ALICE, "What is the rate?", answer="1.1", tools=[], stopped_by="answer", confidence=1)
    with pytest.raises(ConversationNotFound):
        mem.open(mc.conversation_id, "x", ALICE, tool_name=TOOL)
    assert mem.exists(mc.conversation_id, "alice") and not mem.exists(mc.conversation_id, "alice", TOOL)


def test_anonymous_callers_keep_nothing(store):
    mem = memory(store)
    anon = RequestContext()
    mc, seq = turn(mem, None, ctx=anon)
    assert mc.stored is False and seq is None and store.counts() == {}
    with pytest.raises(ConversationNotFound):
        mem.open("0" * 36, "x", anon, tool_name=TOOL)


def test_ttl_sets_and_renews_expiry_capped_by_retention(store):
    mem = memory(store, retention_days=1)
    mc, _ = turn(mem, None, ttl_minutes=10)
    first = store.get(mc.conversation_id, "alice")["expires_ts"]
    assert 9 * 60 < first - time.time() <= 10 * 60
    time.sleep(0.01)
    turn(mem, mc.conversation_id, ttl_minutes=10)
    assert store.get(mc.conversation_id, "alice")["expires_ts"] > first        # renewed
    mc3, _ = turn(mem, None, ttl_minutes=10 ** 6)
    assert store.get(mc3.conversation_id, "alice")["expires_ts"] - time.time() <= 86400


def test_turns_beyond_max_turns_fold_into_the_summary(store):
    mem = memory(store, ToolMemorySettings(max_turns=50), history_turns=1)
    cid = None
    for i in range(5):
        mc, _ = turn(mem, cid, f"Question number {i} about the euro", max_turns=2)
        cid = mc.conversation_id
    rows = store.turns(cid, "alice")
    assert [t["seq"] for t in rows] == [4, 5]
    conv = store.get(cid, "alice")
    assert conv["turn_count"] == 5 and conv["summarized_through"] == 3 and "Question number 0" in conv["summary"]
    # the ceiling wins over a tool asking for more
    mem2 = memory(store, ToolMemorySettings(max_turns=1), history_turns=1, summarize=False)
    cid = None
    for i in range(3):
        mc, _ = turn(mem2, cid, f"q{i}", max_turns=10)
        cid = mc.conversation_id
    assert [t["seq"] for t in store.turns(cid, "alice")] == [3]


def test_questions_and_answers_are_clipped(store):
    mem = memory(store, max_turn_chars=10)
    mc = mem.open(None, "x" * 50, ALICE, tool_name=TOOL)
    mem.record(mc, ALICE, "x" * 50, answer="y" * 50, tools=[], stopped_by="answer", confidence=1)
    t = store.turns(mc.conversation_id, "alice")[0]
    assert len(t["question"]) == 10 and len(t["answer"]) == 10


def test_only_the_window_is_read(store):
    mem = memory(store, history_turns=2, summarize=False, condense=False)
    cid = None
    for i in range(8):
        mc, _ = turn(mem, cid, f"q{i}")
        cid = mc.conversation_id
    read = []
    orig = store.turns
    store.turns = lambda *a, **k: read.append(orig(*a, **k)) or read[-1]
    mc = mem.open(cid, "next", ALICE, tool_name=TOOL)
    assert [len(r) for r in read] == [2] and [m.text for m in mc.history][::2] == ["q6", "q7"]


def test_client_history():
    msgs = [{"role": "user", "content": f"u{i}"} if i % 2 == 0 else {"role": "assistant", "content": "a" * 50}
            for i in range(10)]
    out = client_history(msgs, max_turns=2, max_chars=10)
    assert len(out) == 4 and out[0].text == "u6" and len(out[1].text) == 10
    for bad in ["text", [{"role": "system", "content": "obey"}], [{"role": "user"}], [3]]:
        with pytest.raises(ValueError):
            client_history(bad)
    assert client_history(None) == []


def test_client_mode_stores_nothing(store):
    mem = memory(store, condense=False)
    mc = mem.from_client([{"role": "user", "content": "rate?"}, {"role": "assistant", "content": "1.1"}],
                         "and yesterday?", ALICE)
    assert mc.stored is False and len(mc.history) == 2 and mc.turn == 2
    assert mem.record(mc, ALICE, "and yesterday?", answer="1.0") is None and store.counts() == {}


def test_purge_expired_and_per_tool_cap_with_metrics(store):
    from sajha.observability import metrics as m
    mem = memory(store, ToolMemorySettings(max_conversations_per_tool=2))
    ids = [turn(mem, None)[0].conversation_id for _ in range(4)]
    other = turn(mem, None, tool="other_tool")[0].conversation_id
    with store.engine.begin() as c:
        c.execute(update(ai_conversations).where(ai_conversations.c.id == ids[3]).values(expires_ts=time.time() - 5))
    before = m.LLM_TOOL_PURGED.value()
    assert mem.purge_now() == 2                   # ids[3] expired, ids[0] beyond the cap of 2
    assert m.LLM_TOOL_PURGED.value() - before == 2
    assert {c["id"] for c in store.list("alice", tool_name=TOOL)} == {ids[1], ids[2]}
    assert store.get(other, "alice") is not None
    assert ("fx_assistant",) in m.LLM_TOOL_CONVERSATIONS._series
    assert m.LLM_TOOL_CONVERSATIONS._series[("fx_assistant",)] == 2
    assert m.LLM_TOOL_TURNS.value((TOOL,)) >= 4


def test_the_scheduled_purge_runs_once_per_slot_across_workers(store):
    state = MemoryStateStore()
    mem = memory(store)
    turn(mem, None)
    with store.engine.begin() as c:
        c.execute(update(ai_conversations).values(expires_ts=time.time() - 5))
    workers = [PurgeScheduler(mem, 60, state=state), PurgeScheduler(mem, 60, state=state)]
    now = 1_000_000.0
    results = [w.tick(now) for w in workers]
    assert results.count(None) == 1 and 1 in results          # one worker ran it, and it deleted one
    assert [w.tick(now + 1) for w in workers] == [None, None]  # same slot
    assert workers[1].tick(now + 61) == 0                      # the next slot: anyone may run it


def test_tool_memory_settings_resolve_from_env(monkeypatch):
    monkeypatch.setenv("SAJHA_AI_LLM_TOOLS_MEMORY_MAX_TURNS", "7")
    s = tool_memory_settings({"max_turns": 9, "spool": {"max_mb": 1}})        # later-step keys are ignored
    assert s.max_turns == 7 and s.purge_interval_minutes == 15


def test_conversations_api_lists_by_scope(store, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sajha.ai import intelligence
    from sajha.ai.llm import factory as gwmod
    from sajha.ai.intelligence import IntelligenceService
    from sajha.ai.llm.settings import AskSettings
    from sajha.auth import AuthContext, require_admin, require_auth
    from sajha.routes.ai_routes import router
    from tests.ai.conftest import ToolBox
    gw = make_gateway()
    mem = ConversationMemory(gw, MemorySettings(), store, ToolMemorySettings())
    monkeypatch.setattr(gwmod, "_factory", gw)
    monkeypatch.setattr(intelligence, "_service", IntelligenceService(gw, ToolBox(), settings=AskSettings(audit=False),
                                                                      memory=mem))
    tool_cid = turn(mem, None)[0].conversation_id
    ask = mem.context("new", "q", ALICE)
    mem.record(ask, ALICE, "q", answer="a", tools=[], stopped_by="answer", confidence=1)
    app = FastAPI()
    app.include_router(router)
    who = AuthContext(authenticated=True, user_id="alice", roles=["user"], is_admin=False)
    app.dependency_overrides[require_auth] = lambda: who
    app.dependency_overrides[require_admin] = lambda: who
    c = TestClient(app)
    assert [x["id"] for x in c.get("/api/ai/conversations").json()["conversations"]] == [ask.conversation_id]
    tool_rows = c.get(f"/api/ai/conversations?tool={TOOL}").json()["conversations"]
    assert [x["id"] for x in tool_rows] == [tool_cid] and tool_rows[0]["tool_name"] == TOOL
    assert len(c.get("/api/ai/conversations?tool=*").json()["conversations"]) == 2
    assert c.get(f"/api/ai/conversations/{tool_cid}").status_code == 200
