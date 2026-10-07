"""The RAG store contract (sajha/ai/rag/stores.py ``VectorStore``): every shipped store passes these
cases. pgvector runs only when SAJHA_TEST_POSTGRES_URL names a PostgreSQL database with the vector
extension available (the fixture creates and drops ``rag_chunks``). A third-party store can reuse
the cases by adding itself to ``make_store``. Also: the registry (ai.rag.store selection, ``auto``
fallback and its notice, per-store options from config and env, ``package.module:Class``) and the
index on the sqlite_vec store (separate file, query purpose, batching, dimension-change rebuild)."""

import os
import sqlite3

import pytest

from sajha.ai.llm.settings import RagSettings
from sajha.ai.rag import registry
from sajha.ai.rag.sqlite_vec import SqliteVecStore
from sajha.ai.rag.stores import DimensionChanged, InProcessVectorStore, PgVectorStore, StoredChunk, VectorStore

HAS_VEC = SqliteVecStore.probe({}) is None
PG_URL = os.environ.get("SAJHA_TEST_POSTGRES_URL", "")
STORES = ["memory", pytest.param("sqlite_vec", marks=pytest.mark.skipif(not HAS_VEC, reason="sqlite-vec not loadable")),
          pytest.param("pgvector", marks=pytest.mark.skipif(not PG_URL, reason="SAJHA_TEST_POSTGRES_URL not set"))]


@pytest.fixture(params=STORES)
def store(request, tmp_path):
    s = make_store(request.param, tmp_path)
    yield s
    if request.param == "pgvector":
        from sqlalchemy import text
        with s.engine.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS rag_chunks"))
    s.close()


def make_store(name, tmp_path) -> VectorStore:
    if name == "memory":
        return InProcessVectorStore()
    if name == "sqlite_vec":
        return SqliteVecStore(str(tmp_path / "rag" / "vectors.db"))
    from sqlalchemy import create_engine, text
    eng = create_engine(PG_URL)
    with eng.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        c.execute(text("DROP TABLE IF EXISTS rag_chunks"))
        c.execute(text("CREATE TABLE rag_chunks (id VARCHAR(64) PRIMARY KEY, source VARCHAR(200) NOT NULL, "
                       "document VARCHAR(1000) NOT NULL, doc_hash VARCHAR(64) NOT NULL, embedder VARCHAR(200) NOT NULL, "
                       "ordinal INTEGER NOT NULL, title VARCHAR(500), heading VARCHAR(1000), anchor VARCHAR(300), "
                       "url VARCHAR(1000), text TEXT NOT NULL, embedding vector NOT NULL)"))
    return PgVectorStore.create({"dsn": PG_URL})


def chunk(cid, source, doc, text, vec=(), heading=""):
    return StoredChunk(cid, source, doc, doc.title(), heading, "", f"/d/{doc}", text, int(cid[-1:] or 0)
                       if cid[-1:].isdigit() else 0, list(vec))


def gen(*chunks):
    """The index hands stores a generator: it must be read once, in order."""
    yield from chunks


def seed(store, embedder="e"):
    v = embedder != ""
    store.replace_document("kb", "alpha", "h1", embedder, gen(
        chunk("a1", "kb", "alpha", "The flux capacitor needs 1.21 gigawatts.", (1, 0, 0) if v else ()),
        chunk("a2", "kb", "alpha", "Widgets are blue by default.", (0, 1, 0) if v else ())))
    store.replace_document("notes", "beta", "h2", embedder, gen(
        chunk("b1", "notes", "beta", "The zebra protocol renews every ninety days.", (0, 0, 1) if v else ())))


def test_an_empty_store(store):
    assert store.documents() == {} and store.embedder() == ""
    assert store.search([1, 0, 0], 5) == [] and store.keyword_search("flux", 5) == []
    assert list(store.chunks()) == []
    assert store.stats()["store"] == store.name and store.stats()["documents"] == 0


def test_documents_hashes_and_embedder(store):
    seed(store)
    assert store.documents() == {("kb", "alpha"): "h1", ("notes", "beta"): "h2"}
    assert store.embedder() == "e"
    assert sorted(c.id for c in store.chunks()) == ["a1", "a2", "b1"]
    assert store.stats()["documents"] == 2


def test_vector_search_ranks_by_cosine_and_filters_sources(store):
    seed(store)
    hits = store.search([0.9, 0.1, 0], 2)
    assert [c.id for c, _ in hits] == ["a1", "a2"]
    assert hits[0][1] > hits[1][1] and hits[0][1] == pytest.approx(0.9939, abs=1e-3)
    c = hits[0][0]
    assert (c.source, c.document, c.text, c.url) == ("kb", "alpha", "The flux capacitor needs 1.21 gigawatts.", "/d/alpha")
    assert store.search([1, 0, 0], 1)[0][1] == pytest.approx(1.0, abs=1e-5)
    assert [c.id for c, _ in store.search([1, 0, 0], 5, ["notes"])] == ["b1"]
    assert store.search([1, 0, 0], 5, ["nope"]) == []


def test_keyword_search_ranks_and_filters_sources(store):
    seed(store)
    hits = store.keyword_search("zebra protocol", 5)
    assert hits and hits[0][0].id == "b1"
    assert store.keyword_search("flux capacitor gigawatts", 1)[0][0].id == "a1"
    assert store.keyword_search("zebra", 5, ["kb"]) == []
    assert store.keyword_search("the of and", 5) == []           # stop-words only
    assert store.keyword_search('"; DROP TABLE x --', 5) == []     # no terms survive


def test_replace_delete_and_clear(store):
    seed(store)
    store.replace_document("kb", "alpha", "h3", "e", gen(chunk("c1", "kb", "alpha", "Sprockets turn left.", (1, 0, 0))))
    assert store.documents()[("kb", "alpha")] == "h3"
    assert store.keyword_search("flux", 5) == [] and store.keyword_search("sprockets", 5)[0][0].id == "c1"
    assert [c.id for c, _ in store.search([1, 0, 0], 5)][0] == "c1"
    assert {c.id for c, _ in store.search([1, 0, 0], 5)} == {"c1", "b1"}
    store.delete_document("notes", "beta")
    assert ("notes", "beta") not in store.documents() and store.keyword_search("zebra", 5) == []
    store.clear()
    assert store.documents() == {} and store.search([1, 0, 0], 5) == []


def test_a_failed_replace_leaves_the_document_unchanged(store):
    seed(store)

    def broken():
        yield chunk("x1", "kb", "alpha", "Half written.", (1, 0, 0))
        raise RuntimeError("embedder went away")
    with pytest.raises(RuntimeError):
        store.replace_document("kb", "alpha", "h9", "e", broken())
    assert store.documents()[("kb", "alpha")] == "h1"
    assert store.keyword_search("flux", 1)[0][0].id == "a1"


def test_a_new_embedder_clears_the_store_and_a_new_dimension_is_refused(store):
    seed(store)
    with pytest.raises(DimensionChanged):
        store.replace_document("kb", "gamma", "h4", "e", gen(chunk("g1", "kb", "gamma", "Four dims.", (1, 0, 0, 0))))
    assert ("kb", "gamma") not in store.documents()
    store.replace_document("kb", "gamma", "h4", "other", gen(chunk("g1", "kb", "gamma", "Four dims.", (1, 0, 0, 0))))
    assert store.documents() == {("kb", "gamma"): "h4"} and store.embedder() == "other"
    assert store.search([1, 0, 0, 0], 1)[0][0].id == "g1"


def test_keyword_only(store):
    seed(store, embedder="")
    assert store.embedder() == "" and store.search([1, 0, 0], 5) == []
    assert store.keyword_search("zebra protocol", 1)[0][0].id == "b1"


# ── the sqlite_vec store ─────────────────────────────────────────

needs_vec = pytest.mark.skipif(not HAS_VEC, reason="sqlite-vec not loadable")


@needs_vec
def test_sqlite_vec_keeps_a_file_of_its_own(tmp_path):
    path = tmp_path / "rag" / "vectors.db"
    s = SqliteVecStore(str(path))
    seed(s)
    s.close()
    con = sqlite3.connect(path)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
    assert {"rag_documents", "rag_chunks", "rag_fts", "rag_vec", "rag_meta"} <= names
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    meta = dict(con.execute("SELECT key, value FROM rag_meta"))
    assert meta["embedder"] == "e" and meta["dim"] == "3"
    con.close()
    again = SqliteVecStore(str(path))                  # reopened: everything is still there
    assert again.documents() == {("kb", "alpha"): "h1", ("notes", "beta"): "h2"}
    assert again.search([0, 0, 1], 1)[0][0].id == "b1"
    again.close()


@needs_vec
def test_sqlite_vec_refuses_sajha_s_own_database(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    db = tmp_path / "sajha.db"
    eng = create_engine(f"sqlite:///{db}")
    monkeypatch.setattr("sajha.db.engine.get_engine", lambda: eng)
    with pytest.raises(registry.StoreUnavailable, match="own database"):
        SqliteVecStore(str(db))


@needs_vec
def test_sqlite_vec_throw_away_store_when_persist_is_off(tmp_path):
    s = SqliteVecStore.create({"path": str(tmp_path / "kept.db")}, RagSettings(persist=False))
    path = s.path
    assert s.temporary and os.path.exists(path) and not (tmp_path / "kept.db").exists()
    s.close()
    assert not os.path.exists(path)


@needs_vec
def test_sqlite_vec_searches_while_another_thread_writes(tmp_path):
    import threading
    s = SqliteVecStore(str(tmp_path / "v.db"))
    seed(s)
    out = []
    t = threading.Thread(target=lambda: out.append(s.keyword_search("zebra", 1)[0][0].id))
    t.start()
    t.join()
    assert out == ["b1"]
    s.close()


# ── the registry ─────────────────────────────────────────────────

def test_the_shipped_stores_are_registered():
    names = registry.registered_stores()
    assert {"memory", "sqlite_vec", "pgvector"} <= set(names)
    assert registry.store_class("tests.ai.test_rag_store_contract:TinyStore") is TinyStore
    with pytest.raises(ValueError, match="unknown ai.rag.store"):
        registry.store_class("nope")


class TinyStore(InProcessVectorStore):
    """A third-party store named as package.module:Class."""
    name = "tiny"
    defaults = {"flavour": "plain"}

    @classmethod
    def create(cls, options, settings=None, engine=None):
        s = cls()
        s.options = options
        return s


def test_store_options_layer_defaults_config_and_env():
    st = RagSettings(store="tests.ai.test_rag_store_contract:TinyStore",
                     stores={"tiny": {"flavour": "config", "size": 2}})
    store, reason = registry.select_store(st, environ={"SAJHA_AI_RAG_STORES_TINY_SIZE": "3"})
    assert reason is None and isinstance(store, TinyStore)
    store2, _ = registry.select_store(st, environ={})
    assert store2.options == {"flavour": "config", "size": 2}
    assert registry.store_options("tiny", TinyStore, st, {"SAJHA_AI_RAG_STORES_TINY_SIZE": "3"}) == \
        {"flavour": "config", "size": "3"}
    assert registry.store_options("sqlite_vec", SqliteVecStore, RagSettings(),
                                  {"SAJHA_AI_RAG_STORES_SQLITE_VEC_PATH": "/x/v.db"}) == {"path": "/x/v.db"}


def test_auto_falls_back_to_memory_with_a_notice(monkeypatch):
    raised = []
    monkeypatch.setattr("sajha.notices.raise_notice", lambda nid, **kw: raised.append((nid, kw)))
    monkeypatch.setattr(SqliteVecStore, "probe", classmethod(lambda cls, o: "no extensions here"))
    store, reason = registry.select_store(RagSettings(store="auto", persist=False))
    assert store.name == "memory" and reason == "no extensions here"
    assert raised[0][0] == registry.NOTICE_ID and "no extensions here" in raised[0][1]["detail"]
    store, reason = registry.select_store(RagSettings(store="sqlite_vec", persist=False))
    assert store.name == "memory" and "no extensions here" in reason and len(raised) == 2


def test_pgvector_without_postgres_falls_back(tmp_path, monkeypatch):
    monkeypatch.setattr("sajha.notices.raise_notice", lambda *a, **k: None)
    store, reason = registry.select_store(RagSettings(store="pgvector", persist=False),
                                          environ={"SAJHA_AI_RAG_STORES_PGVECTOR_DSN": f"sqlite:///{tmp_path}/x.db"})
    assert store.name == "memory" and "rag_chunks" in reason


def test_pgvector_keyword_sql():
    from sqlalchemy import create_engine
    from sqlalchemy.dialects import postgresql
    s = PgVectorStore(create_engine("sqlite://"))
    sql = str(s.keyword_statement("Flux capacitor, the power!", 4, ["kb"]).compile(dialect=postgresql.dialect()))
    assert "to_tsquery('english'::regconfig" in sql and "ts_rank_cd" in sql and "@@" in sql and "LIMIT" in sql
    assert s.keyword_statement("the of", 4) is None
    with pytest.raises(ValueError):
        PgVectorStore(create_engine("sqlite://"), text_search_config="x'; drop")


# ── the index on sqlite_vec ──────────────────────────────────────

class RecordingGateway:
    """Wraps the mock factory and records each embeddings call's size and purpose."""

    def __init__(self, gw):
        self.gw, self.calls = gw, []
        self.settings = gw.settings

    def model(self, alias, kind=""):
        inner, calls = self.gw.model(alias, kind=kind), self.calls

        class Recording:
            def info(self):
                return inner.info()

            def embeddings_create(self, request=None, /, **fields):
                sj = fields.get("sajha")
                calls.append((len(fields.get("input") or []), sj.input_purpose if sj else None))
                return inner.embeddings_create(request, **fields)
        return Recording()


@needs_vec
def test_the_index_on_sqlite_vec(tmp_path, monkeypatch):
    from sajha.ai.rag.index import DocIndex
    from sajha.core.storage import LocalStorageBackend
    from tests.ai.conftest import make_gateway
    st = LocalStorageBackend(str(tmp_path))
    monkeypatch.setattr("sajha.ai.rag.index._storage", lambda: st)
    st.write_text("kb/widgets.md", "# Widgets\n\n## Power\n\nThe flux capacitor needs 1.21 gigawatts.\n\n"
                  + "\n\n".join(f"## Part {i}\n\nFiller paragraph number {i} about sprockets." for i in range(12)))
    st.write_text("kb/notes.txt", "The zebra protocol renews every ninety days.")
    gw = RecordingGateway(make_gateway())
    path = tmp_path / "vec" / "vectors.db"
    settings = RagSettings(index_sajha_docs=False, store="sqlite_vec", stores={"sqlite_vec": {"path": str(path)}},
                           sources=[{"name": "kb", "path": "kb", "pattern": "*"}], embed_batch_size=2, chunk_chars=60,
                           chunk_overlap=0)
    idx = DocIndex(settings, gw)
    assert idx.store.name == "sqlite_vec" and idx.store_fallback is None
    stats = idx.build()
    assert stats["store"] == "sqlite_vec" and stats["indexed"] == 2 and stats["chunks"] > 4
    assert all(n <= 2 and p == "document" for n, p in gw.calls)            # batches of embed_batch_size
    gw.calls.clear()
    hit = idx.search("how much power does the flux capacitor need", 2)[0]
    assert hit["document"] == "kb/widgets.md" and "gigawatts" in hit["text"]
    assert gw.calls == [(1, "query")]                                       # the query uses the query purpose
    assert idx.search("zebra protocol", 1, sources=["kb"])[0]["document"] == "kb/notes.txt"
    assert path.exists() and idx.stats()["chunks"] == stats["chunks"]
    idx.close()
    again = DocIndex(settings, gw)                                          # a restart re-embeds nothing
    assert again.build()["unchanged"] == 2
    # the same embedder name now gives other dimensions: a clean rebuild, not a broken index
    monkeypatch.setattr(again, "_embed", lambda texts, purpose="document": [[1.0, 0.0] for _ in texts])
    s = again.build()
    assert s["unchanged"] == 2                    # hashes unchanged: nothing to embed, nothing breaks
    s = again.build(force=True)
    assert s["indexed"] == 2 and again.store.dimensions() == 2
    again.close()


@needs_vec
def test_keyword_only_index_on_sqlite_vec(tmp_path, monkeypatch):
    from sajha.ai.rag.index import DocIndex
    from sajha.core.storage import LocalStorageBackend
    st = LocalStorageBackend(str(tmp_path))
    monkeypatch.setattr("sajha.ai.rag.index._storage", lambda: st)
    st.write_text("kb/notes.txt", "The zebra protocol renews every ninety days.")
    idx = DocIndex(RagSettings(index_sajha_docs=False, store="sqlite_vec", persist=False, embedding_model="none",
                               sources=[{"name": "kb", "path": "kb", "pattern": "*"}]), None)
    assert idx.build()["embedder"] == "none (BM25 only)"
    assert idx.search("zebra", 1)[0]["document"] == "kb/notes.txt"
    con = sqlite3.connect(idx.store.path)
    assert con.execute("SELECT 1 FROM sqlite_master WHERE name = 'rag_vec'").fetchone() is None
    con.close()
    idx.close()


@needs_vec
def test_a_dimension_change_mid_build_rebuilds(tmp_path, monkeypatch):
    from sajha.ai.rag.index import DocIndex
    from sajha.core.storage import LocalStorageBackend
    from tests.ai.conftest import make_gateway
    st = LocalStorageBackend(str(tmp_path))
    monkeypatch.setattr("sajha.ai.rag.index._storage", lambda: st)
    st.write_text("kb/a.txt", "Alpha text about apples.")
    st.write_text("kb/b.txt", "Beta text about bananas.")
    idx = DocIndex(RagSettings(index_sajha_docs=False, store="sqlite_vec", persist=False,
                               sources=[{"name": "kb", "path": "kb", "pattern": "*"}]), make_gateway())
    idx.build()
    st.write_text("kb/b.txt", "Beta text about blueberries.")             # one changed document ...
    monkeypatch.setattr(idx, "_embed", lambda texts, purpose="document": [[0.6, 0.8] for _ in texts])
    s = idx.build()                                                       # ... in a new dimension
    assert s["indexed"] == 2 and idx.store.dimensions() == 2              # everything re-embedded
    idx.close()
