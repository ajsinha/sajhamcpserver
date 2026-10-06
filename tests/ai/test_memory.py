"""Conversation memory (sajha/ai/memory.py): multi-turn asks with follow-ups rewritten to stand alone,
older turns summarised through the gateway, per-user privacy, retention, and the delete-my-history
endpoints. Mock provider only; each test has its own SQLite database."""

import time

import pytest
from sqlalchemy import create_engine

from sajha.ai.intelligence import IntelligenceService
from sajha.ai.llm import RequestContext
from sajha.ai.llm.settings import AskSettings, MemorySettings
from sajha.ai.memory import ConversationMemory, ConversationNotFound, ConversationStore, NEW
from tests.ai.conftest import make_gateway

PCT = "What is the percentage change from 80 to 100?"


@pytest.fixture
def store(tmp_path):
    return ConversationStore(create_engine(f"sqlite:///{tmp_path / 'm.db'}"))


def service(toolbox, store, gw=None, planner="react", **mem):
    gw = gw or make_gateway()
    memory = ConversationMemory(gw, MemorySettings(**mem), store)
    return IntelligenceService(gw, toolbox, settings=AskSettings(audit=False, planner=planner), memory=memory)


def spy(gw):
    seen = []
    orig = gw.chat

    def chat(request, **kw):
        seen.append(request)
        return orig(request, **kw)
    gw.chat = chat
    return seen


@pytest.mark.parametrize("planner", ["react", "plan_execute"])
def test_a_follow_up_uses_the_earlier_turn(toolbox, store, planner):
    gw = make_gateway()
    svc = service(toolbox, store, gw, planner=planner)
    u = RequestContext(user_id="alice")
    r1 = svc.ask(PCT, u, conversation_id=NEW)
    assert r1.conversation_id and r1.turn == 1 and "25" in r1.answer
    seen = spy(gw)
    r2 = svc.ask("And from 100 to 150?", u, conversation_id=r1.conversation_id)
    assert r2.conversation_id == r1.conversation_id and r2.turn == 2
    assert r2.standalone_question == "What is the percentage change from 100 to 150?"
    assert r2.steps[0].name == "calc_percentage_change" and r2.steps[0].arguments == {"old_value": 100, "new_value": 150}
    assert "50" in r2.answer
    planning = [r for r in seen if r.tools]
    assert planning and planning[0].messages[0].text == PCT          # the earlier turn is context
    turns = store.turns(r1.conversation_id, "alice")
    assert [t["question"] for t in turns] == [PCT, "And from 100 to 150?"]
    assert turns[1]["standalone"] == "What is the percentage change from 100 to 150?"


def test_without_a_conversation_id_nothing_is_kept(toolbox, store):
    r = service(toolbox, store).ask(PCT, RequestContext(user_id="alice"))
    assert r.conversation_id is None and store.list("alice") == []


def test_conversations_are_never_shared_across_users(toolbox, store):
    svc = service(toolbox, store)
    r1 = svc.ask(PCT, RequestContext(user_id="alice"), conversation_id=NEW)
    cid = r1.conversation_id
    assert store.get(cid, "mallory") is None and store.turns(cid, "mallory") == []
    with pytest.raises(ConversationNotFound):
        svc.memory.context(cid, "and 100 to 150?", RequestContext(user_id="mallory"))
    gw = make_gateway()
    seen = spy(gw)
    r2 = service(toolbox, store, gw).ask("And from 100 to 150?", RequestContext(user_id="mallory"),
                                         conversation_id=cid)
    assert r2.conversation_id != cid and any("not found" in c for c in r2.caveats)
    assert all(PCT not in (m.text or "") for r in seen for m in r.messages)     # nothing of alice's leaked
    with pytest.raises(ConversationNotFound):
        store.add_turn(cid, "mallory", question="x", standalone="", answer="", tools=[], stopped_by="answer",
                       confidence=0)
    assert store.delete(cid, "mallory") is False
    assert store.delete_all("mallory") == 1                                      # only her own new one
    assert len(store.turns(cid, "alice")) == 1
    assert service(toolbox, store).ask(PCT, RequestContext(), conversation_id=NEW).conversation_id is None


def test_older_turns_are_summarised_through_the_gateway(toolbox, store):
    gw = make_gateway()
    svc = service(toolbox, store, gw, history_turns=1)
    u = RequestContext(user_id="alice")
    cid = svc.ask(PCT, u, conversation_id=NEW).conversation_id
    svc.ask("What is the future value of 5000 at 7 percent for 20 years?", u, conversation_id=cid)
    seen = spy(gw)
    r = svc.ask("Compound interest on a principal of 1000 at rate 5 for 10 years", u, conversation_id=cid)
    conv = store.get(cid, "alice")
    assert conv["summarized_through"] == 1 and PCT in conv["summary"]
    assert any(req.response_schema and "summary" in req.response_schema["properties"] for req in seen)
    planning = [req for req in seen if req.tools][0]
    assert "Earlier in this conversation" in planning.system and PCT in planning.system
    assert [m.text for m in planning.messages if m.role == "user"][0].startswith("What is the future value")
    assert r.turn == 3 and r.usage.total_tokens > 0


def test_retention_and_per_user_cap(toolbox, store):
    svc = service(toolbox, store)
    u = RequestContext(user_id="alice")
    ids = [svc.ask(PCT, u, conversation_id=NEW).conversation_id for _ in range(3)]
    from sajha.ai.memory import ai_conversations
    from sqlalchemy import update
    with store.engine.begin() as c:
        c.execute(update(ai_conversations).where(ai_conversations.c.id == ids[0])
                  .values(updated_ts=time.time() - 40 * 86400))
    assert store.purge(30, 0) == 1 and store.get(ids[0], "alice") is None
    assert store.purge(30, 1) == 1 and [c["id"] for c in store.list("alice")] == [ids[2]]
    assert store.turns(ids[1], "alice") == []


def test_memory_can_be_switched_off(toolbox, store):
    r = service(toolbox, store, enabled=False).ask(PCT, RequestContext(user_id="alice"), conversation_id=NEW)
    assert r.conversation_id is None and store.list("alice") == []


# ── the routes ───────────────────────────────────────────────────

def _client(toolbox, store, monkeypatch, user="alice"):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sajha.ai import gateway as gwmod, intelligence
    from sajha.auth import AuthContext, require_admin, require_auth
    from sajha.routes.ai_routes import router
    gw = make_gateway()
    monkeypatch.setattr(gwmod, "_gateway", gw)
    monkeypatch.setattr(intelligence, "_service", service(toolbox, store, gw))
    app = FastAPI()
    app.include_router(router)
    who = AuthContext(authenticated=True, user_id=user, roles=["user"], is_admin=False)
    app.dependency_overrides[require_auth] = lambda: who
    app.dependency_overrides[require_admin] = lambda: who
    return TestClient(app)


def test_routes_conversations_and_delete_my_history(toolbox, store, monkeypatch):
    alice = _client(toolbox, store, monkeypatch)
    body = alice.post("/api/ai/ask", json={"question": PCT, "conversation_id": "new"}).json()
    cid = body["conversation_id"]
    assert cid and body["turn"] == 1
    body = alice.post("/api/ai/ask", json={"question": "And from 100 to 150?", "conversation_id": cid}).json()
    assert body["turn"] == 2 and "50" in body["answer"]
    lst = alice.get("/api/ai/conversations").json()
    assert [c["id"] for c in lst["conversations"]] == [cid] and lst["conversations"][0]["turns"] == 2
    one = alice.get(f"/api/ai/conversations/{cid}").json()
    assert [t["question"] for t in one["turns"]] == [PCT, "And from 100 to 150?"]
    assert alice.post("/api/ai/ask", json={"question": "x", "conversation_id": "bad id!"}).status_code == 400

    bob = _client(toolbox, store, monkeypatch, user="bob")
    assert bob.get(f"/api/ai/conversations/{cid}").status_code == 404
    assert bob.post("/api/ai/ask", json={"question": "and 1 to 2?", "conversation_id": cid}).status_code == 404
    assert bob.delete(f"/api/ai/conversations/{cid}").status_code == 404
    assert bob.delete("/api/ai/conversations").json() == {"deleted": 0}
    assert bob.get("/api/ai/conversations").json()["conversations"] == []

    alice = _client(toolbox, store, monkeypatch)
    assert alice.delete("/api/ai/conversations").json() == {"deleted": 1}
    assert alice.get("/api/ai/conversations").json()["conversations"] == []
    assert alice.post("/api/ai/ask", json={"question": PCT, "conversation_id": cid}).status_code == 404


def test_route_stream_carries_the_conversation_id(toolbox, store, monkeypatch):
    import json as _json
    c = _client(toolbox, store, monkeypatch)
    with c.stream("POST", "/api/ai/ask?stream=1", json={"question": PCT, "conversation_id": "new"}) as r:
        text = "".join(r.iter_text())
    done = [_json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")][-1]
    assert done["type"] == "done" and done["result"]["conversation_id"]
