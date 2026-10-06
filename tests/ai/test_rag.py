"""Document retrieval (sajha/ai/rag): chunking with section anchors, the index over SAJHA's guides and
admin sources (incremental by content hash), uploads, the in-process store's persistence, the
pgvector store's SQL, the sajha_search_docs tool (alone and through the ask loop) and the
"Ask the docs" route. Mock embeddings only."""

import json

import pytest

from sajha.ai.llm import RequestContext
from sajha.ai.llm.settings import AskSettings, RagSettings
from sajha.ai.rag import chunking
from sajha.ai.rag.index import DocIndex, SAJHA_DOCS, UPLOADS, set_doc_index
from sajha.ai.rag.stores import InProcessVectorStore, PgVectorStore, StoredChunk, pgvector_available
from sajha.core.storage import LocalStorageBackend
from tests.ai.conftest import ToolBox, make_gateway

DOC = """# Widget Guide

Intro paragraph about widgets and what they do for you.

## Configuring widgets

Set `widgets.colour` to blue. The flux capacitor needs 1.21 gigawatts to run properly.

```yaml
widgets:
  colour: blue
```

## Removing widgets

Delete the widget file and restart the server; the sprocket index rebuilds itself.
"""


@pytest.fixture
def storage(tmp_path, monkeypatch):
    st = LocalStorageBackend(str(tmp_path))
    monkeypatch.setattr("sajha.ai.rag.index._storage", lambda: st)
    st.write_text("kb/widgets.md", DOC)
    st.write_text("kb/notes.txt", "Quarterly notes. The zebra protocol renews every ninety days.")
    return st


def index(storage, **kw):
    cfg = {"index_sajha_docs": False, "persist": False, "store": "memory",
           "sources": [{"name": "kb", "path": "kb", "pattern": "*"}], **kw}
    return DocIndex(RagSettings(**cfg), make_gateway())


def test_markdown_chunks_carry_their_section_and_anchor():
    chunks = chunking.chunk_markdown(DOC, size=200, overlap=20)
    heads = [c.heading for c in chunks]
    assert "Configuring widgets" in heads and "Removing widgets" in heads
    conf = next(c for c in chunks if c.heading == "Configuring widgets")
    assert conf.anchor == "configuring-widgets" and "```yaml" in conf.text and "colour: blue" in conf.text
    long = chunking.chunk_text("word " * 2000, size=300, overlap=30)
    assert len(long) > 5 and all(len(c.text) <= 460 for c in long)
    assert chunking.html_to_text("<p>a &amp; b</p><script>x()</script>") == "a & b"


def test_search_cites_the_document_and_section(storage):
    idx = index(storage)
    stats = idx.build()
    assert stats["documents"] == 2 and stats["indexed"] == 2 and stats["embedder"] == "mock/mock-embed"
    hits = idx.search("how much power does the flux capacitor need?", 3)
    assert hits[0]["document"] == "kb/widgets.md" and hits[0]["section"] == "Configuring widgets"
    assert hits[0]["citation"] == 1 and hits[0]["source"] == "kb" and "1.21 gigawatts" in hits[0]["text"]
    assert idx.search("zebra protocol renewal", 1)[0]["document"] == "kb/notes.txt"
    assert idx.search("zebra protocol", 2, sources=["nope"]) == []


def test_the_index_syncs_by_content_hash(storage):
    idx = index(storage)
    idx.build()
    assert idx.build()["unchanged"] == 2
    storage.write_text("kb/notes.txt", "Quarterly notes. The okapi protocol renews every ninety days.")
    s = idx.build()
    assert s["indexed"] == 1 and s["unchanged"] == 1
    assert idx.search("okapi protocol", 1)[0]["document"] == "kb/notes.txt"
    storage.delete("kb/notes.txt")
    assert idx.build()["removed"] == 1
    assert all(h["document"] != "kb/notes.txt" for h in idx.search("okapi protocol", 5))


def test_lexical_only_without_an_embedder(storage):
    idx = index(storage, embedding_model="none")
    assert idx.build()["embedder"] == "none (BM25 only)"
    assert idx.search("flux capacitor gigawatts", 1)[0]["document"] == "kb/widgets.md"


def test_uploads(storage):
    idx = index(storage)
    idx.build()
    out = idx.save_upload("../../Runbook.md", b"# Runbook\n\nRotate the quokka keys every Tuesday morning.")
    assert out["document"] == "data/rag/uploads/Runbook.md" and out["chunks"] == 1
    hit = idx.search("when are the quokka keys rotated", 1)[0]
    assert hit["source"] == UPLOADS and hit["title"] == "Runbook"
    with pytest.raises(ValueError):
        idx.save_upload("evil.exe", b"MZ")
    with pytest.raises(ValueError):
        idx.save_upload("bin.txt", b"\xff\xfe\x00")             # not UTF-8 text
    assert idx.delete_upload("Runbook.md") is True and idx.delete_upload("Runbook.md") is False
    assert all(h["source"] != UPLOADS for h in idx.search("quokka keys", 5))


def test_in_process_store_persists_through_storage(storage):
    idx = index(storage, persist=True, index_path="rag/index.json")
    idx.build()
    assert storage.exists("rag/index.json")
    again = index(storage, persist=True, index_path="rag/index.json")
    s = again.build()
    assert s["unchanged"] == 2 and s["indexed"] == 0          # nothing re-embedded after a restart
    assert again.search("flux capacitor", 1)[0]["document"] == "kb/widgets.md"
    st = InProcessVectorStore()
    st.replace_document("a", "d", "h", "e", [StoredChunk("1", "a", "d", "T", "", "", "", "x", 0, [0.6, 0.8])])
    assert st.search([0.6, 0.8], 1)[0][1] == pytest.approx(1.0)


def test_sajha_docs_are_indexed_with_help_links():
    idx = DocIndex(RagSettings(persist=False, store="memory"), make_gateway())
    hits = idx.search("MRTR requestState", 5, sources=[SAJHA_DOCS])
    assert hits and all(h["source"] == SAJHA_DOCS for h in hits)
    top = hits[0]
    assert top["url"].startswith("/help/guides/") and "#" in top["url"]


def test_pgvector_store_sql_and_detection(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.dialects import postgresql
    eng = create_engine(f"sqlite:///{tmp_path / 'x.db'}")
    assert pgvector_available(eng) is False and pgvector_available(None) is False
    assert DocIndex(RagSettings(store="pgvector", persist=False), None, engine=eng).store.name == "memory"
    stmt = PgVectorStore(eng).search_statement([0.0, 1.0], 3, ["kb"])
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "<=>" in sql and "rag_chunks" in sql and "LIMIT" in sql


def test_the_tool_and_the_ask_loop(storage, monkeypatch):
    from sajha.ai.intelligence import IntelligenceService
    from sajha.ai.rag.tool import SajhaSearchDocsTool
    idx = index(storage)
    set_doc_index(idx)
    try:
        cfg = json.load(open("config/tools/sajha_search_docs.json"))
        tool = SajhaSearchDocsTool(cfg)
        out = tool.execute({"query": "flux capacitor power", "top_k": 2})
        assert out["count"] == 2 and out["results"][0]["section"] == "Configuring widgets"
        tb = ToolBox()
        tb.add(tool)
        svc = IntelligenceService(make_gateway(), tb, settings=AskSettings(audit=False))
        r = svc.ask("Search the documentation: how much power does the flux capacitor need?",
                    RequestContext(user_id="u"))
        assert [s.name for s in r.steps] == ["sajha_search_docs"] and "1.21 gigawatts" in r.answer
    finally:
        set_doc_index(None)
    with pytest.raises(RuntimeError, match="off"):
        SajhaSearchDocsTool().execute({"query": "x"})


def test_ask_the_docs_route(storage, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sajha.auth import AuthContext, require_admin, require_auth
    from sajha.routes.ai_routes import router
    idx = index(storage)
    set_doc_index(idx)
    try:
        app = FastAPI()
        app.include_router(router)

        class Who(AuthContext):
            def has_tool_access(self, name):
                return self.is_admin

        admin = Who(authenticated=True, user_id="admin", roles=["admin"], is_admin=True)
        user = Who(authenticated=True, user_id="bob", roles=["user"], is_admin=False)
        app.dependency_overrides[require_auth] = lambda: admin
        app.dependency_overrides[require_admin] = lambda: admin
        c = TestClient(app)
        body = c.post("/api/ai/docs/search", json={"query": "flux capacitor"}).json()
        assert body["results"][0]["document"] == "kb/widgets.md"
        assert c.post("/api/ai/docs/search", json={}).status_code == 400
        up = c.post("/api/ai/docs/uploads", json={"filename": "faq.md", "content": "# FAQ\n\nThe wombat port is 7777."})
        assert up.status_code == 201
        assert c.post("/api/ai/docs/search", json={"query": "wombat port", "source": "uploads"}).json()["count"] == 1
        assert c.get("/api/ai/docs/status").json()["documents"] == 3
        assert c.delete("/api/ai/docs/uploads/faq.md").status_code == 200
        app.dependency_overrides[require_auth] = lambda: user
        assert c.post("/api/ai/docs/search", json={"query": "flux", "source": "kb"}).status_code == 403
        assert c.post("/api/ai/docs/search", json={"query": "flux capacitor"}).json()["results"] == []   # guides only
    finally:
        set_doc_index(None)
