"""
SAJHA MCP Server — RAG: vector stores.
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

A ``VectorStore`` keeps passages with their embeddings, grouped by document, and answers a
cosine-similarity search. Two implementations:

* ``InProcessVectorStore`` (the default): pure Python (no numpy), in memory, persisted through
  the storage backend (local | s3 | azure | gcs) as one JSON file with each vector packed as
  base64 float32, so a restart re-embeds only documents that changed.
* ``PgVectorStore``: a ``rag_chunks`` table with a pgvector ``vector`` column, used when the
  database is PostgreSQL, the ``vector`` extension is installed and the table exists. SAJHA
  runs no DDL on PostgreSQL: the table is an optional section of
  db/scripts/postgresql/schema.sql that a DBA runs. Queries are SQLAlchemy expressions.
"""

from __future__ import annotations

import base64
import logging
import math
import threading
from array import array
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
    vector: List[float] = field(default_factory=list)


def normalize(v: Iterable[float]) -> List[float]:
    v = [float(x) for x in v]
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else v


def _pack(v: List[float]) -> str:
    return base64.b64encode(array("f", v).tobytes()).decode("ascii")


def _unpack(s: str) -> List[float]:
    a = array("f")
    a.frombytes(base64.b64decode(s))
    return a.tolist()


class VectorStore:
    name = "base"

    def documents(self) -> Dict[Tuple[str, str], str]:
        """{(source, document): content hash} of what is stored."""
        raise NotImplementedError

    def replace_document(self, source: str, document: str, doc_hash: str, embedder: str,
                         chunks: List[StoredChunk]) -> None:
        raise NotImplementedError

    def delete_document(self, source: str, document: str) -> None:
        raise NotImplementedError

    def search(self, vector: List[float], top_k: int, sources: Optional[List[str]] = None
               ) -> List[Tuple[StoredChunk, float]]:
        raise NotImplementedError

    def chunks(self) -> List[StoredChunk]:
        """Every stored passage (text and metadata; vectors may be omitted)."""
        raise NotImplementedError

    def embedder(self) -> str:
        return ""

    def clear(self) -> None:
        raise NotImplementedError

    def save(self) -> None:
        """Persist, where the store needs it."""

    def stats(self) -> Dict[str, Any]:
        docs = self.documents()
        return {"store": self.name, "documents": len(docs),
                "sources": sorted({s for s, _ in docs})}


class InProcessVectorStore(VectorStore):
    name = "memory"
    VERSION = 1

    def __init__(self, persist_path: Optional[str] = None, storage=None):
        self.persist_path = persist_path
        self._storage = storage            # () -> StorageBackend; default: sajha.core.storage.get_storage
        self._lock = threading.RLock()
        self._docs: Dict[Tuple[str, str], Dict[str, Any]] = {}   # key -> {hash, embedder, chunks}
        self._embedder = ""
        self._dirty = False

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
        docs = {}
        for d in data.get("documents", []):
            chunks = [StoredChunk(c["id"], d["source"], d["document"], d.get("title", ""), c.get("heading", ""),
                                  c.get("anchor", ""), d.get("url", "") + (("#" + c["anchor"]) if d.get("url")
                                                                         and c.get("anchor") else ""),
                                  c["text"], c.get("ordinal", 0), _unpack(c["v"]) if c.get("v") else [])
                      for c in d.get("chunks", [])]
            docs[(d["source"], d["document"])] = {"hash": d["hash"], "chunks": chunks, "title": d.get("title", ""),
                                                  "url": d.get("url", "")}
        with self._lock:
            self._docs, self._embedder, self._dirty = docs, embedder, False
        return True

    def save(self) -> None:
        if not self.persist_path or not self._dirty:
            return
        with self._lock:
            payload = {"version": self.VERSION, "embedder": self._embedder, "documents": [
                {"source": s, "document": d, "hash": v["hash"], "title": v.get("title", ""), "url": v.get("url", ""),
                 "chunks": [{"id": c.id, "heading": c.heading, "anchor": c.anchor, "text": c.text,
                             "ordinal": c.ordinal, "v": _pack(c.vector) if c.vector else ""} for c in v["chunks"]]}
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
        with self._lock:
            if self._embedder and embedder != self._embedder:
                self._docs.clear()
            self._embedder = embedder
            title = chunks[0].title if chunks else ""
            url = chunks[0].url.split("#", 1)[0] if chunks else ""
            self._docs[(source, document)] = {"hash": doc_hash, "chunks": list(chunks), "title": title, "url": url}
            self._dirty = True

    def delete_document(self, source, document):
        with self._lock:
            if self._docs.pop((source, document), None) is not None:
                self._dirty = True

    def clear(self):
        with self._lock:
            self._docs.clear()
            self._dirty = True

    def chunks(self):
        with self._lock:
            return [c for v in self._docs.values() for c in v["chunks"]]

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
                    if not c.vector or len(c.vector) != len(q):
                        continue
                    scored.append((sum(a * b for a, b in zip(q, c.vector)), c))
        scored.sort(key=lambda x: -x[0])
        return [(c, s) for s, c in scored[:top_k]]


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
    name = "pgvector"

    def __init__(self, engine):
        self.engine = engine
        self.t = _pg_table()

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

    def replace_document(self, source, document, doc_hash, embedder, chunks):
        from sqlalchemy import and_, delete, insert
        t = self.t
        with self.engine.begin() as c:
            c.execute(delete(t).where(and_(t.c.source == source, t.c.document == document)))
            if chunks:
                c.execute(insert(t), [{"id": ch.id, "source": source, "document": document, "doc_hash": doc_hash,
                                       "embedder": embedder, "ordinal": ch.ordinal, "title": ch.title[:500],
                                       "heading": ch.heading[:1000], "anchor": ch.anchor[:300], "url": ch.url[:1000],
                                       "text": ch.text, "embedding": ch.vector} for ch in chunks])

    def delete_document(self, source, document):
        from sqlalchemy import and_, delete
        with self.engine.begin() as c:
            c.execute(delete(self.t).where(and_(self.t.c.source == source, self.t.c.document == document)))

    def clear(self):
        from sqlalchemy import delete
        with self.engine.begin() as c:
            c.execute(delete(self.t))

    def chunks(self):
        from sqlalchemy import select
        t = self.t
        with self.engine.connect() as c:
            rows = c.execute(select(t.c.id, t.c.source, t.c.document, t.c.title, t.c.heading, t.c.anchor, t.c.url,
                                    t.c.text, t.c.ordinal)).all()
        return [StoredChunk(r[0], r[1], r[2], r[3] or "", r[4] or "", r[5] or "", r[6] or "", r[7], r[8])
                for r in rows]

    def search_statement(self, vector, top_k, sources=None):
        from sqlalchemy import select
        t = self.t
        dist = t.c.embedding.cosine_distance(normalize(vector)).label("distance")
        stmt = select(t.c.id, t.c.source, t.c.document, t.c.title, t.c.heading, t.c.anchor, t.c.url, t.c.text,
                      t.c.ordinal, dist).order_by(dist).limit(top_k)
        if sources:
            stmt = stmt.where(t.c.source.in_(list(sources)))
        return stmt

    def search(self, vector, top_k, sources=None):
        with self.engine.connect() as c:
            rows = c.execute(self.search_statement(vector, top_k, sources)).all()
        return [(StoredChunk(r[0], r[1], r[2], r[3] or "", r[4] or "", r[5] or "", r[6] or "", r[7], r[8]),
                 1.0 - float(r[9])) for r in rows]
