"""
SAJHA MCP Server — RAG: the document index behind ``sajha_search_docs`` and "Ask the docs".
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

What is indexed (``ai.rag``):

* ``sajha_docs``: SAJHA's own guides (every guide the help pages serve: docs/** without the
  archive and READMEs), each passage citing ``/help/guides/<name>#<section>``;
* each ``ai.rag.sources`` entry: the files matching ``pattern`` under ``path`` in the storage
  backend (local | s3 | azure | gcs);
* ``uploads``: files an admin uploads (``POST /api/ai/docs/uploads``), kept under
  ``ai.rag.uploads_dir`` in the storage backend.

Documents are split into passages (chunking.py), embedded through the gateway's
``ai.rag.embedding_model`` alias (``embedding``, served by ``mock/mock-embed`` out of the box)
and kept in a vector store (stores.py): pgvector when PostgreSQL has it, else in process.
A search fuses the vector ranking with a BM25 ranking of the same passages (reciprocal rank
fusion), so it works with no embedder at all (``embedding_model: none``). The index syncs by
content hash: only changed documents are re-embedded.
"""

from __future__ import annotations

import hashlib
import logging
import posixpath
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from sajha.ai.lexical import BM25Index
from sajha.ai.llm.settings import RagSettings
from sajha.ai.rag.chunking import TEXT_TYPES, chunk_document, title_of
from sajha.ai.rag.stores import (InProcessVectorStore, PgVectorStore, StoredChunk, VectorStore, normalize,
                                 pgvector_available)

logger = logging.getLogger(__name__)

SAJHA_DOCS = "sajha_docs"
UPLOADS = "uploads"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")
_RRF_K = 60


def _storage():
    from sajha.core.storage import get_storage
    return get_storage()


def safe_upload_name(name: str) -> str:
    base = posixpath.basename((name or "").replace("\\", "/")).strip()
    base = _SAFE_NAME.sub("_", base).strip(" .")
    if not base or not base.lower().endswith(TEXT_TYPES):
        raise ValueError(f"unsupported file {name!r}: upload one of {', '.join(TEXT_TYPES)}")
    return base[:150]


class DocIndex:
    def __init__(self, settings: Optional[RagSettings] = None, gateway=None, engine=None,
                 store: Optional[VectorStore] = None):
        self.settings = settings or RagSettings()
        self.gateway = gateway
        self._engine = engine
        self.store = store or self._choose_store()
        self._bm25 = BM25Index()
        self._bm25_ids: Dict[str, StoredChunk] = {}
        self._bm25_stale = True
        self._lock = threading.RLock()
        self._built = threading.Event()
        self._building = False
        self.last_build: Dict[str, Any] = {}

    # ── setup ───────────────────────────────────────────────────
    def _choose_store(self) -> VectorStore:
        mode = self.settings.store
        engine = self._engine
        if mode in ("auto", "pgvector") and engine is None:
            try:
                from sajha.db.engine import get_engine
                engine = get_engine()
            except Exception:
                engine = None
        if mode in ("auto", "pgvector") and pgvector_available(engine):
            logger.info("  RAG: pgvector store (rag_chunks)")
            return PgVectorStore(engine)
        if mode == "pgvector":
            logger.warning("  RAG: ai.rag.store is pgvector but PostgreSQL has no vector extension or no "
                           "rag_chunks table (see the optional section of db/scripts/postgresql/schema.sql); "
                           "using the in-process store")
        return InProcessVectorStore(self.settings.index_path if self.settings.persist else None,
                                    storage=lambda: _storage())

    def embedder_name(self) -> str:
        alias = (self.settings.embedding_model or "").strip()
        if not alias or alias.lower() == "none" or self.gateway is None:
            return ""
        try:
            return self.gateway.embedding_model(alias).qualified_id
        except Exception as e:
            logger.info(f"rag: no embedding model for {alias!r} ({e}); lexical search only")
            return ""

    def _embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), 64):
            vecs = self.gateway.embed(texts[i:i + 64], model=self.settings.embedding_model)
            out.extend(normalize(v) for v in vecs)
        return out

    # ── documents ───────────────────────────────────────────────
    def discover(self) -> List[Dict[str, Any]]:
        """Every document to index: {source, document, title, url, text}."""
        st = _storage()
        docs: List[Dict[str, Any]] = []
        if self.settings.index_sajha_docs:
            from sajha.web.guides import guide_files, guide_url
            for rel in guide_files():
                try:
                    text = st.read_text(rel)
                except Exception:
                    continue
                name = rel.rsplit("/", 1)[-1]
                docs.append({"source": SAJHA_DOCS, "document": rel, "title": title_of(name, text),
                             "url": guide_url(name), "text": text})
        for src in self.settings.sources:
            try:
                files = st.list_files(src.path.rstrip("/"), src.pattern)
            except Exception as e:
                logger.warning(f"rag: source {src.name}: cannot list {src.path}: {e}")
                continue
            for rel in files:
                if not rel.lower().endswith(TEXT_TYPES):
                    continue
                try:
                    text = st.read_text(rel)
                except Exception as e:
                    logger.warning(f"rag: source {src.name}: cannot read {rel}: {e}")
                    continue
                docs.append({"source": src.name, "document": rel, "title": title_of(rel, text),
                             "url": "", "text": text})
        for rel in self.uploads():
            try:
                text = st.read_text(rel)
            except Exception:
                continue
            docs.append({"source": UPLOADS, "document": rel, "title": title_of(rel, text), "url": "", "text": text})
        return docs

    def uploads(self) -> List[str]:
        d = self.settings.uploads_dir.rstrip("/")
        try:
            return [r for r in _storage().list_files(d, "*") if r.lower().endswith(TEXT_TYPES)]
        except Exception:
            return []

    def _doc_hash(self, text: str) -> str:
        s = self.settings
        return hashlib.sha256(f"{s.chunk_chars}\x00{s.chunk_overlap}\x00{text}".encode("utf-8")).hexdigest()

    # ── building ────────────────────────────────────────────────
    def build(self, force: bool = False) -> Dict[str, Any]:
        """Sync the store with the documents: embed new and changed ones, drop removed ones."""
        with self._lock:
            if self._building:
                return {"status": "already building"}
            self._building = True
        t0 = time.time()
        stats = {"documents": 0, "indexed": 0, "unchanged": 0, "removed": 0, "chunks": 0, "errors": []}
        try:
            embedder = self.embedder_name()
            if isinstance(self.store, InProcessVectorStore) and not self.store.documents():
                self.store.load(embedder)
            if force or self.store.embedder() not in ("", embedder):
                self.store.clear()
            have = self.store.documents()
            docs = self.discover()
            stats["documents"] = len(docs)
            seen = set()
            for d in docs:
                key = (d["source"], d["document"])
                seen.add(key)
                h = self._doc_hash(d["text"])
                if have.get(key) == h:
                    stats["unchanged"] += 1
                    continue
                try:
                    n = self._index_document(d, h, embedder)
                    stats["indexed"] += 1
                    stats["chunks"] += n
                except Exception as e:
                    stats["errors"].append(f"{d['document']}: {e}"[:300])
                    logger.warning(f"rag: cannot index {d['document']}: {e}")
            for key in set(have) - seen:
                self.store.delete_document(*key)
                stats["removed"] += 1
            self.store.save()
            self._bm25_stale = True
            stats.update(embedder=embedder or "none (BM25 only)", store=self.store.name,
                         duration_ms=int((time.time() - t0) * 1000), at=time.time())
            self.last_build = stats
            logger.info(f"  RAG: {stats['documents']} documents ({stats['indexed']} indexed, {stats['unchanged']} "
                        f"unchanged, {stats['removed']} removed) in {stats['duration_ms']} ms, "
                        f"store={self.store.name}, embedder={stats['embedder']}")
            return stats
        finally:
            with self._lock:
                self._building = False
            self._built.set()

    def _index_document(self, d: Dict[str, Any], doc_hash: str, embedder: str) -> int:
        s = self.settings
        pieces = chunk_document(d["document"], d["text"], s.chunk_chars, s.chunk_overlap)
        chunks = []
        for p in pieces:
            cid = hashlib.sha1(f"{d['source']}\x00{d['document']}\x00{p.ordinal}\x00{doc_hash}".encode()).hexdigest()[:32]
            url = d["url"] + ("#" + p.anchor if d["url"] and p.anchor else "")
            chunks.append(StoredChunk(cid, d["source"], d["document"], d["title"], p.heading, p.anchor, url, p.text,
                                      p.ordinal))
        if embedder and chunks:
            vecs = self._embed([f"{c.title} — {c.heading}\n{c.text}" for c in chunks])
            for c, v in zip(chunks, vecs or []):
                c.vector = v
        self.store.replace_document(d["source"], d["document"], doc_hash, embedder, chunks)
        return len(chunks)

    def build_in_background(self) -> None:
        threading.Thread(target=self._safe_build, name="rag-index-build", daemon=True).start()

    def _safe_build(self) -> None:
        try:
            self.build()
        except Exception as e:
            logger.warning(f"  RAG: index build failed: {e}", exc_info=True)
            self._built.set()

    def ensure_built(self, wait_s: float = 60.0) -> None:
        if self._built.is_set():
            return
        if not self._building:
            self._safe_build()
        else:
            self._built.wait(wait_s)

    # ── searching ───────────────────────────────────────────────
    def _lexical(self) -> BM25Index:
        if self._bm25_stale:
            with self._lock:
                if self._bm25_stale:
                    chunks = self.store.chunks()
                    self._bm25_ids = {c.id: c for c in chunks}
                    self._bm25.build({c.id: (f"{c.title} {c.heading} {c.text}", {}) for c in chunks})
                    self._bm25_stale = False
        return self._bm25

    def search(self, query: str, top_k: Optional[int] = None, sources: Optional[List[str]] = None
               ) -> List[Dict[str, Any]]:
        """The passages that best answer ``query``, best first, each with its citation."""
        query = (query or "").strip()
        if not query:
            return []
        self.ensure_built()
        k = max(1, min(int(top_k or self.settings.top_k), 20))
        pool = k * 4
        ranked: Dict[str, float] = {}
        found: Dict[str, StoredChunk] = {}
        embedder = self.store.embedder()
        if embedder and self.gateway is not None:
            try:
                qv = self._embed([query])[0]
                w = max(0.0, float(self.settings.vector_weight))
                for rank, (c, _score) in enumerate(self.store.search(qv, pool, sources)):
                    ranked[c.id] = ranked.get(c.id, 0.0) + w / (_RRF_K + rank + 1)
                    found[c.id] = c
            except Exception as e:
                logger.info(f"rag: vector search failed ({e}); lexical only")
        lex = self._lexical()
        hits = [h for h in lex.search(query, pool * 3)
                if not sources or self._bm25_ids.get(h[0], StoredChunk("", "", "", "", "", "", "", "")).source in sources]
        for rank, (cid, _d, _c, _cat) in enumerate(hits[:pool]):
            ranked[cid] = ranked.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
            found.setdefault(cid, self._bm25_ids.get(cid))
        best = sorted((cid for cid in ranked if found.get(cid) is not None), key=lambda c: -ranked[c])[:k]
        top = ranked[best[0]] if best else 1.0
        out = []
        for i, cid in enumerate(best):
            c = found[cid]
            out.append({"citation": i + 1, "source": c.source, "document": c.document, "title": c.title,
                        "section": c.heading, "url": c.url or None, "score": round(ranked[cid] / top, 4),
                        "text": c.text if len(c.text) <= 1500 else c.text[:1499] + "…"})
        return out

    # ── uploads ─────────────────────────────────────────────────
    def save_upload(self, filename: str, data: bytes) -> Dict[str, Any]:
        name = safe_upload_name(filename)
        if len(data) > self.settings.max_upload_bytes:
            raise ValueError(f"file is larger than ai.rag.max_upload_bytes ({self.settings.max_upload_bytes})")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("file is not UTF-8 text")
        rel = f"{self.settings.uploads_dir.rstrip('/')}/{name}"
        _storage().write_text(rel, text)
        d = {"source": UPLOADS, "document": rel, "title": title_of(rel, text), "url": "", "text": text}
        n = self._index_document(d, self._doc_hash(text), self.store.embedder() or self.embedder_name())
        self.store.save()
        self._bm25_stale = True
        return {"document": rel, "title": d["title"], "chunks": n}

    def delete_upload(self, filename: str) -> bool:
        name = safe_upload_name(filename)
        rel = f"{self.settings.uploads_dir.rstrip('/')}/{name}"
        st = _storage()
        if not st.exists(rel):
            return False
        st.delete(rel)
        self.store.delete_document(UPLOADS, rel)
        self.store.save()
        self._bm25_stale = True
        return True

    def stats(self) -> Dict[str, Any]:
        out = self.store.stats()
        out.update(embedder=self.store.embedder() or "none (BM25 only)", built=self._built.is_set(),
                   building=self._building, last_build=self.last_build, uploads=self.uploads(),
                   configured_sources=[s.model_dump() for s in self.settings.sources],
                   index_sajha_docs=self.settings.index_sajha_docs)
        return out


# ── singleton ─────────────────────────────────────────────────────

_index: Optional[DocIndex] = None


def init_doc_index(settings: Optional[RagSettings] = None, gateway=None) -> Optional[DocIndex]:
    global _index
    settings = settings or RagSettings()
    if not settings.enabled:
        _index = None
        return None
    _index = DocIndex(settings, gateway)
    if settings.build_on_start:
        _index.build_in_background()
    return _index


def get_doc_index() -> Optional[DocIndex]:
    return _index


def set_doc_index(index: Optional[DocIndex]) -> None:
    global _index
    _index = index
