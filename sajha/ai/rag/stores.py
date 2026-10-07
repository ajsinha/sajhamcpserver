"""
SAJHA MCP Server — RAG: the store contract and the stores that ship with SAJHA.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A store keeps passages (``StoredChunk``) grouped by document, with each document's content
hash and the embedder that produced its vectors, and answers two searches: nearest
neighbours of a query vector (``search``) and a keyword (BM25-style) ranking
(``keyword_search``). DocIndex (index.py) fuses the two. ``ai.rag.store`` picks the store
by name (registry.py); this module defines the contract and two of the shipped stores:

* ``InProcessVectorStore`` (``memory``): pure Python, in memory, persisted through the storage
  backend as one JSON file (``ai.rag.index_path``). Every passage's text and vector stay in
  RAM (vectors as float32 arrays: 4 bytes per dimension), and the keyword side is an
  in-process BM25 index over every passage, so its memory grows with the corpus: for small
  setups and tests.
* ``PgVectorStore`` (``pgvector``): a ``rag_chunks`` table with a pgvector ``vector`` column
  (an optional section of db/scripts/postgresql/schema.sql that a DBA runs; SAJHA runs no DDL
  on PostgreSQL). Vector and keyword searches (PostgreSQL full-text search) run in the
  database and return only the top k rows.

sqlite_vec.py holds ``SqliteVecStore`` (``sqlite_vec``, the default): a SQLite file of its
own with sqlite-vec for the vectors and FTS5 for the keywords.

Writing a store: subclass ``VectorStore``, implement the abstract methods, and register it
(``registry.register_store``, the ``sajha.rag.stores`` entry-point group, or name it as
``package.module:Class`` in ``ai.rag.store``). tests/ai/test_rag_store_contract.py is the
contract every shipped store passes; run it against yours.
"""

from __future__ import annotations

import base64
import logging
import math
import threading
from array import array
from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass
class StoredChunk:
    id: str
    source: str                           # "sajha_docs", a configured source name, or "uploads"
    document: str                         # the document's path (unique within the source)
    title: str
    heading: str
    anchor: str
    url: str
    text: str
    ordinal: int = 0
    vector: Sequence[float] = field(default_factory=list)


class StoreUnavailable(RuntimeError):
    """The store cannot run here (a missing package, extension, table or permission)."""


class DimensionChanged(ValueError):
    """A vector's dimension differs from the stored ones under the same embedder name: the
    index must be rebuilt (DocIndex clears the store and builds again)."""


def normalize(v: Iterable[float]) -> List[float]:
    v = [float(x) for x in v]
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


def _pack(v: Sequence[float]) -> str:
    return base64.b64encode(array("f", v).tobytes()).decode("ascii")


def _unpack(s: str) -> array:
    a = array("f")
    a.frombytes(base64.b64decode(s))
    return a


def keyword_terms(query: str) -> List[str]:
    """The query's search terms: lower-case alphanumeric tokens, stop-words dropped, de-duplicated."""
    from sajha.ai.lexical import tokenize
    return list(dict.fromkeys(tokenize(query or "")))


class VectorStore:
    """The store contract. A store is created by the registry with ``create(options, settings,
    engine)`` and used from several threads (the background build and searches)."""

    name: ClassVar[str] = "base"
    #: settings under ``ai.rag.stores.<name>``, merged under the configured ones
    defaults: ClassVar[Dict[str, Any]] = {}

    # ── lifecycle ───────────────────────────────────────────────
    @classmethod
    def probe(cls, options: Dict[str, Any]) -> Optional[str]:
        """None when the store can run here, else the reason it cannot (``auto`` uses this)."""
        return None

    @classmethod
    def create(cls, options: Dict[str, Any], settings: Any = None, engine: Any = None) -> "VectorStore":
        """Build the store from its ``ai.rag.stores.<name>`` options and the ``ai.rag`` settings.
        Raise ``StoreUnavailable`` when it cannot run."""
        return cls(**options)

    def load(self, embedder: str) -> bool:
        """Load persisted state for ``embedder`` when the store keeps it outside itself."""
        return False

    def save(self) -> None:
        """Persist, where the store needs it (called after each build and upload)."""

    def close(self) -> None:
        """Release connections and files."""

    # ── writing ─────────────────────────────────────────────────
    def documents(self) -> Dict[Tuple[str, str], str]:
        """{(source, document): content hash} of what is stored (metadata only)."""
        raise NotImplementedError

    def embedder(self) -> str:
        """The embedder of the stored vectors ("" for keyword-only or empty)."""
        return ""

    def replace_document(self, source: str, document: str, doc_hash: str, embedder: str,
                         chunks: Iterable[StoredChunk]) -> int:
        """Replace a document's passages atomically. ``chunks`` may be a generator (the index
        embeds batch by batch while the store consumes it): read it once, in order. A different
        ``embedder`` than the stored one clears the store first; a vector dimension that differs
        under the same embedder raises ``DimensionChanged``. Returns the number stored."""
        raise NotImplementedError

    def delete_document(self, source: str, document: str) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    # ── reading ─────────────────────────────────────────────────
    def search(self, vector: Sequence[float], top_k: int, sources: Optional[List[str]] = None
               ) -> List[Tuple[StoredChunk, float]]:
        """The ``top_k`` passages nearest ``vector`` by cosine similarity, best first, with the
        similarity (1 = identical). Only passages of ``sources`` when given."""
        raise NotImplementedError

    def keyword_search(self, query: str, top_k: int, sources: Optional[List[str]] = None
                       ) -> List[Tuple[StoredChunk, float]]:
        """The ``top_k`` passages that best match ``query``'s words (BM25-style), best first,
        with a score (higher is better; comparable only within one call). The default is an
        in-process BM25 index over ``chunks()``, rebuilt when ``documents()`` changes: a store
        that can rank keywords itself should override this."""
        if not keyword_terms(query):
            return []
        bm25, by_id = self._fallback_bm25()
        hits = []
        for cid, _desc, score, _cat in bm25.search(query, len(by_id) if sources else top_k):
            c = by_id.get(cid)
            if c is not None and (not sources or c.source in sources):
                hits.append((c, float(score)))
                if len(hits) >= top_k:
                    break
        return hits

    def chunks(self) -> Iterator[StoredChunk]:
        """Every stored passage (text and metadata; vectors may be omitted)."""
        raise NotImplementedError

    def stats(self) -> Dict[str, Any]:
        docs = self.documents()
        return {"store": self.name, "documents": len(docs),
                "sources": sorted({s for s, _ in docs})}

    # ── the default keyword side ────────────────────────────────
    def _fallback_bm25(self):
        from sajha.ai.lexical import BM25Index
        key = hash(frozenset(self.documents().items()))
        cached = getattr(self, "_bm25_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1], cached[2]
        lock = self.__dict__.setdefault("_bm25_lock", threading.Lock())
        with lock:
            cached = getattr(self, "_bm25_cache", None)
            if cached is not None and cached[0] == key:
                return cached[1], cached[2]
            by_id = {}
            items = {}
            for c in self.chunks():
                c = StoredChunk(c.id, c.source, c.document, c.title, c.heading, c.anchor, c.url, c.text, c.ordinal)
                by_id[c.id] = c
                items[c.id] = (f"{c.title} {c.heading} {c.text}", {})
            bm25 = BM25Index()
            bm25.build(items)
            self._bm25_cache = (key, bm25, by_id)
            return bm25, by_id


class InProcessVectorStore(VectorStore):
    name = "memory"
    VERSION = 1

    def __init__(self, persist_path: Optional[str] = None, storage=None):
        self.persist_path = persist_path
        self._storage = storage            # () -> StorageBackend; default: sajha.core.storage.get_storage
        self._lock = threading.RLock()
        self._docs: Dict[Tuple[str, str], Dict[str, Any]] = {}   # key -> {hash, chunks, title, url}
        self._embedder = ""
        self._dim = 0
        self._dirty = False

    @classmethod
    def create(cls, options, settings=None, engine=None):
        path = options.get("path")
        if path is None and settings is not None:
            path = settings.index_path if settings.persist else None
        return cls(path or None, storage=options.get("storage"))

    def _backend(self):
        if self._storage is not None:
            return self._storage()
        from sajha.core.storage import get_storage
        return get_storage()

    def load(self, embedder: str) -> bool:
        if not self.persist_path:
            return False
        try:
            st = self._backend()
            if not st.exists(self.persist_path):
                return False
            data = st.read_json(self.persist_path)
        except Exception as e:
            logger.warning(f"rag: cannot load the index ({e}); rebuilding")
            return False
        if data.get("version") != self.VERSION or data.get("embedder") != embedder:
            return False
        docs, dim = {}, 0
        for d in data.get("documents", []):
            chunks = []
            for c in d.get("chunks", []):
                vec = _unpack(c["v"]) if c.get("v") else array("f")
                dim = dim or len(vec)
                chunks.append(StoredChunk(c["id"], d["source"], d["document"], d.get("title", ""), c.get("heading", ""),
                                          c.get("anchor", ""), d.get("url", "") + (("#" + c["anchor"]) if d.get("url")
                                                                                 and c.get("anchor") else ""),
                                          c["text"], c.get("ordinal", 0), vec))
            docs[(d["source"], d["document"])] = {"hash": d["hash"], "chunks": chunks, "title": d.get("title", ""),
                                                  "url": d.get("url", "")}
        with self._lock:
            self._docs, self._embedder, self._dim, self._dirty = docs, embedder, dim, False
        return True

    def save(self) -> None:
        if not self.persist_path or not self._dirty:
            return
        with self._lock:
            payload = {"version": self.VERSION, "embedder": self._embedder, "documents": [
                {"source": s, "document": d, "hash": v["hash"], "title": v.get("title", ""), "url": v.get("url", ""),
                 "chunks": [{"id": c.id, "heading": c.heading, "anchor": c.anchor, "text": c.text,
                             "ordinal": c.ordinal, "v": _pack(c.vector) if len(c.vector) else ""} for c in v["chunks"]]}
                for (s, d), v in self._docs.items()]}
            self._dirty = False
        try:
            self._backend().write_json(self.persist_path, payload, indent=0)
        except Exception as e:
            logger.warning(f"rag: cannot persist the index: {e}")

    def documents(self):
        with self._lock:
            return {k: v["hash"] for k, v in self._docs.items()}

    def embedder(self) -> str:
        return self._embedder

    def replace_document(self, source, document, doc_hash, embedder, chunks):
        kept = []
        dim = 0
        for c in chunks:
            if len(c.vector):
                c.vector = c.vector if isinstance(c.vector, array) else array("f", c.vector)
                dim = dim or len(c.vector)
            kept.append(c)
        with self._lock:
            if self._embedder != embedder and self._docs:
                self._docs.clear()
                self._dim = 0
            if dim and self._dim and dim != self._dim and any(k != (source, document) for k in self._docs):
                raise DimensionChanged(f"vectors of {dim} dimensions; the store holds {self._dim}")
            self._embedder = embedder
            self._dim = dim or self._dim
            title = kept[0].title if kept else ""
            url = kept[0].url.split("#", 1)[0] if kept else ""
            self._docs[(source, document)] = {"hash": doc_hash, "chunks": kept, "title": title, "url": url}
            self._dirty = True
        return len(kept)

    def delete_document(self, source, document):
        with self._lock:
            if self._docs.pop((source, document), None) is not None:
                self._dirty = True

    def clear(self):
        with self._lock:
            self._docs.clear()
            self._embedder, self._dim = "", 0
            self._dirty = True

    def chunks(self):
        with self._lock:
            return iter([c for v in self._docs.values() for c in v["chunks"]])

    def search(self, vector, top_k, sources=None):
        q = normalize(vector)
        if not q:
            return []
        scored = []
        with self._lock:
            for (src, _), v in self._docs.items():
                if sources and src not in sources:
                    continue
                for c in v["chunks"]:
                    if len(c.vector) != len(q):
                        continue
                    scored.append((sum(a * b for a, b in zip(q, c.vector)), c))
        scored.sort(key=lambda x: -x[0])
        return [(c, s) for s, c in scored[:top_k]]

    def stats(self):
        out = super().stats()
        with self._lock:
            out.update(chunks=sum(len(v["chunks"]) for v in self._docs.values()), dimensions=self._dim,
                       path=self.persist_path or None)
        return out


# ── pgvector ──────────────────────────────────────────────────────

PG_TABLE = "rag_chunks"      # optional: not in sajha.db.schema.metadatas() (tests/test_db_schema.py)


def _pg_table():
    """``rag_chunks`` (optional; defined in db/scripts/postgresql/schema.sql's pgvector section).
    Not part of sajha.db.schema.metadatas(): the start-up schema check does not require it."""
    from sqlalchemy import Column, Integer, MetaData, String, Table, Text
    from sqlalchemy.types import UserDefinedType

    class Vector(UserDefinedType):
        cache_ok = True

        def get_col_spec(self, **kw):
            return "vector"

        def bind_processor(self, dialect):
            return lambda v: None if v is None else "[" + ",".join(f"{float(x):.7g}" for x in v) + "]"

        def result_processor(self, dialect, coltype):
            def conv(v):
                if v is None or isinstance(v, list):
                    return v
                return [float(x) for x in str(v).strip("[]").split(",") if x.strip()]
            return conv

        class comparator_factory(UserDefinedType.Comparator):
            def cosine_distance(self, other):
                from sqlalchemy.types import Float
                return self.op("<=>", return_type=Float)(other)

    md = MetaData()
    return Table(PG_TABLE, md,
                 Column("id", String(64), primary_key=True),
                 Column("source", String(200), nullable=False),
                 Column("document", String(1000), nullable=False),
                 Column("doc_hash", String(64), nullable=False),
                 Column("embedder", String(200), nullable=False),
                 Column("ordinal", Integer, nullable=False),
                 Column("title", String(500)),
                 Column("heading", String(1000)),
                 Column("anchor", String(300)),
                 Column("url", String(1000)),
                 Column("text", Text, nullable=False),
                 Column("embedding", Vector(), nullable=False))


def pgvector_available(engine) -> bool:
    """PostgreSQL with the ``vector`` extension installed and the ``rag_chunks`` table present."""
    if engine is None or engine.dialect.name != "postgresql":
        return False
    try:
        from sqlalchemy import column, inspect, select, table
        ext = table("pg_extension", column("extname"))
        with engine.connect() as c:
            has_ext = c.execute(select(ext.c.extname).where(ext.c.extname == "vector")).first() is not None
        return has_ext and inspect(engine).has_table(PG_TABLE)
    except Exception as e:
        logger.debug(f"rag: pgvector probe failed: {e}")
        return False


class PgVectorStore(VectorStore):
    """``rag_chunks`` in PostgreSQL with pgvector. ``ai.rag.stores.pgvector.dsn`` names the
    database (a SQLAlchemy URL; put it in the environment, SAJHA_AI_RAG_STORES_PGVECTOR_DSN);
    empty uses SAJHA's own database. Rows are written ``batch_size`` at a time."""
    name = "pgvector"
    defaults = {"dsn": "", "batch_size": 256, "text_search_config": "english"}

    def __init__(self, engine, batch_size: int = 256, text_search_config: str = "english"):
        self.engine = engine
        self.t = _pg_table()
        self.batch_size = max(1, int(batch_size))
        cfg = str(text_search_config or "english")
        if not cfg.replace("_", "").isalnum():
            raise ValueError(f"text_search_config {cfg!r} is not a configuration name")
        self.text_search_config = cfg

    @classmethod
    def create(cls, options, settings=None, engine=None):
        dsn = str(options.get("dsn") or "").strip()
        if dsn:
            from sqlalchemy import create_engine
            engine = create_engine(dsn, pool_pre_ping=True)
        elif engine is None:
            try:
                from sajha.db.engine import get_engine
                engine = get_engine()
            except Exception:
                engine = None
        if not pgvector_available(engine):
            raise StoreUnavailable("the database is not PostgreSQL, or has no vector extension, or no rag_chunks "
                                   "table (see the optional section of db/scripts/postgresql/schema.sql)")
        return cls(engine, options.get("batch_size", 256), options.get("text_search_config", "english"))

    def documents(self):
        from sqlalchemy import select
        t = self.t
        with self.engine.connect() as c:
            rows = c.execute(select(t.c.source, t.c.document, t.c.doc_hash).distinct()).all()
        return {(r[0], r[1]): r[2] for r in rows}

    def embedder(self) -> str:
        from sqlalchemy import select
        with self.engine.connect() as c:
            r = c.execute(select(self.t.c.embedder).limit(1)).first()
        return r[0] if r else ""

    def _dims(self, c, source, document) -> int:
        from sqlalchemy import and_, func, not_, select
        t = self.t
        r = c.execute(select(func.vector_dims(t.c.embedding)).where(
            not_(and_(t.c.source == source, t.c.document == document))).limit(1)).first()
        return int(r[0]) if r and r[0] else 0

    def replace_document(self, source, document, doc_hash, embedder, chunks):
        from sqlalchemy import and_, delete, insert
        t = self.t
        n = 0
        with self.engine.begin() as c:
            from sqlalchemy import select
            r = c.execute(select(t.c.embedder).limit(1)).first()
            stored = r[0] if r else ""
            if stored and stored != embedder:
                c.execute(delete(t))
            c.execute(delete(t).where(and_(t.c.source == source, t.c.document == document)))
            batch: List[Dict[str, Any]] = []
            dims = None
            for ch in chunks:
                if dims is None and len(ch.vector):
                    have = self._dims(c, source, document)
                    if have and have != len(ch.vector):
                        raise DimensionChanged(f"vectors of {len(ch.vector)} dimensions; the store holds {have}")
                    dims = len(ch.vector)
                batch.append({"id": ch.id, "source": source, "document": document, "doc_hash": doc_hash,
                              "embedder": embedder, "ordinal": ch.ordinal, "title": ch.title[:500],
                              "heading": ch.heading[:1000], "anchor": ch.anchor[:300], "url": ch.url[:1000],
                              "text": ch.text, "embedding": list(ch.vector)})
                if len(batch) >= self.batch_size:
                    c.execute(insert(t), batch)
                    n += len(batch)
                    batch = []
            if batch:
                c.execute(insert(t), batch)
                n += len(batch)
        return n

    def delete_document(self, source, document):
        from sqlalchemy import and_, delete
        with self.engine.begin() as c:
            c.execute(delete(self.t).where(and_(self.t.c.source == source, self.t.c.document == document)))

    def clear(self):
        from sqlalchemy import delete
        with self.engine.begin() as c:
            c.execute(delete(self.t))

    def _columns(self):
        t = self.t
        return (t.c.id, t.c.source, t.c.document, t.c.title, t.c.heading, t.c.anchor, t.c.url, t.c.text, t.c.ordinal)

    @staticmethod
    def _chunk(r) -> StoredChunk:
        return StoredChunk(r[0], r[1], r[2], r[3] or "", r[4] or "", r[5] or "", r[6] or "", r[7], r[8])

    def chunks(self):
        from sqlalchemy import select
        with self.engine.connect() as c:
            result = c.execution_options(stream_results=True, yield_per=500).execute(select(*self._columns()))
            for r in result:
                yield self._chunk(r)

    def search_statement(self, vector, top_k, sources=None):
        from sqlalchemy import select
        t = self.t
        dist = t.c.embedding.cosine_distance(normalize(vector)).label("distance")
        stmt = select(*self._columns(), dist).order_by(dist).limit(top_k)
        if sources:
            stmt = stmt.where(t.c.source.in_(list(sources)))
        return stmt

    def search(self, vector, top_k, sources=None):
        with self.engine.connect() as c:
            rows = c.execute(self.search_statement(vector, top_k, sources)).all()
        return [(self._chunk(r), 1.0 - float(r[9])) for r in rows]

    def keyword_statement(self, query, top_k, sources=None):
        """PostgreSQL full-text search over title, heading and text, ranked by ts_rank_cd; the
        terms are OR-ed (any word matches, more and rarer matches rank higher). Add a GIN index
        on the same expression for large corpora (db/scripts/postgresql/schema.sql)."""
        from sqlalchemy import func, literal_column, select
        terms = keyword_terms(query)
        if not terms:
            return None
        t = self.t
        cfg = literal_column(f"'{self.text_search_config}'::regconfig")
        doc = func.to_tsvector(cfg, func.coalesce(t.c.title, "") + " " + func.coalesce(t.c.heading, "") + " " + t.c.text)
        tsq = func.to_tsquery(cfg, " | ".join(terms))
        rank = func.ts_rank_cd(doc, tsq).label("rank")
        stmt = select(*self._columns(), rank).where(doc.op("@@")(tsq)).order_by(rank.desc()).limit(top_k)
        if sources:
            stmt = stmt.where(t.c.source.in_(list(sources)))
        return stmt

    def keyword_search(self, query, top_k, sources=None):
        stmt = self.keyword_statement(query, top_k, sources)
        if stmt is None:
            return []
        with self.engine.connect() as c:
            rows = c.execute(stmt).all()
        return [(self._chunk(r), float(r[9])) for r in rows]

    def stats(self):
        from sqlalchemy import func, select
        out = super().stats()
        try:
            with self.engine.connect() as c:
                out["chunks"] = int(c.execute(select(func.count()).select_from(self.t)).scalar() or 0)
        except Exception:
            pass
        return out
