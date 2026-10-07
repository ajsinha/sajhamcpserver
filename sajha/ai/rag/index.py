"""
SAJHA MCP Server — RAG: the document index behind ``sajha_search_docs`` and "Ask the docs".
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

What is indexed (``ai.rag``):

* ``sajha_docs``: SAJHA's own guides (every guide the help pages serve: docs/** without the
  archive and READMEs), each passage citing ``/help/guides/<name>#<section>``;
* each ``ai.rag.sources`` entry: the files matching ``pattern`` under ``path`` in the storage
  backend (local | s3 | azure | gcs): text (md, txt, rst, html) and, when the optional
  readers are installed, PDF (``pypdf``) and Word ``.docx`` (``python-docx``), see extract.py;
* ``uploads``: files an admin uploads (``POST /api/ai/docs/uploads``), kept under
  ``ai.rag.uploads_dir`` in the storage backend.

Documents are split into passages (chunking.py), embedded through the gateway's
``ai.rag.embedding_model`` alias (``embedding``, served by ``mock/mock-embed`` out of the box)
and kept in the store ``ai.rag.store`` names (registry.py; sqlite_vec by default, a SQLite
file of its own). A search fuses the store's vector ranking with its keyword (BM25) ranking
(reciprocal rank fusion), so it works with no embedder at all (``embedding_model: none``).
Document passages are embedded with the "document" purpose and the query with the "query"
purpose. The index syncs by content hash: only changed documents are re-embedded. A PDF or
Word file is hashed on its bytes, so an unchanged file is skipped before its text is even
extracted. Indexing streams: documents are read one at a time and each document's passages
are embedded ``ai.rag.embed_batch_size`` at a time while the store consumes them, so the
build never holds the corpus in memory (the memory store itself does, by design).
"""

from __future__ import annotations

import hashlib
import logging
import posixpath
import re
import threading
import time
from typing import Any, Dict, Iterator, List, Optional

from sajha.ai.llm.settings import RagSettings
from sajha.ai.rag import extract
from sajha.ai.rag.chunking import SUPPORTED_TYPES, chunk_document, title_of
from sajha.ai.rag.stores import DimensionChanged, StoredChunk, VectorStore, normalize

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
    if not base or not base.lower().endswith(SUPPORTED_TYPES):
        raise ValueError(f"unsupported file {name!r}: upload one of {', '.join(SUPPORTED_TYPES)}")
    return base[:150]


class DocIndex:
    def __init__(self, settings: Optional[RagSettings] = None, gateway=None, engine=None,
                 store: Optional[VectorStore] = None):
        self.settings = settings or RagSettings()
        self.gateway = gateway
        self._engine = engine
        self.store_fallback: Optional[str] = None      # why ai.rag.store is not the store in use
        self.store = store or self._choose_store()
        self._lock = threading.RLock()
        self._built = threading.Event()
        self._building = False
        self.last_build: Dict[str, Any] = {}

    # ── setup ───────────────────────────────────────────────────
    def _choose_store(self) -> VectorStore:
        from sajha.ai.rag.registry import select_store
        store, self.store_fallback = select_store(self.settings, self._engine)
        if getattr(store, "_storage", False) is None:        # the memory store reads through index._storage
            store._storage = lambda: _storage()
        logger.info(f"  RAG: store {store.name}" + (f" (fallback: {self.store_fallback})" if self.store_fallback else ""))
        return store

    def close(self) -> None:
        """Release the store's connections and files."""
        try:
            self.store.close()
        except Exception as e:
            logger.debug(f"rag: closing the store: {e}")

    def embedder_name(self) -> str:
        alias = (self.settings.embedding_model or "").strip()
        if not alias or alias.lower() == "none" or self.gateway is None:
            return ""
        try:
            return self._embedding_model().info().qualified_id
        except Exception as e:
            logger.info(f"rag: no embedding model for {alias!r} ({e}); lexical search only")
            return ""

    def _embedding_model(self):
        """The GovernedModel for ai.rag.embedding_model (an alias or provider/model; anything else
        means the ``embedding`` alias)."""
        alias = (self.settings.embedding_model or "").strip() or "embedding"
        aliases = getattr(getattr(self.gateway, "settings", None), "aliases", {}) or {}
        if alias not in aliases and "/" not in alias:
            alias = "embedding"
        return self.gateway.model(alias, kind="embedding")

    def _embed(self, texts: List[str], purpose: str = "document") -> List[List[float]]:
        """Normalized vectors for ``texts``: passages with purpose "document", a query with "query"."""
        from sajha.ai.llm import SajhaRequest
        out: List[List[float]] = []
        n = max(1, int(self.settings.embed_batch_size or 64))
        model = self._embedding_model()
        for i in range(0, len(texts), n):
            resp = model.embeddings_create(input=list(texts[i:i + n]), sajha=SajhaRequest(input_purpose=purpose))
            out.extend(normalize(v) for v in resp.vectors)
        return out

    # ── documents ───────────────────────────────────────────────
    def _file(self, source: str, rel: str) -> Dict[str, Any]:
        """A document from storage. Text is read now; a PDF or Word file is hashed on its bytes
        and its text extracted only when the hash says it changed (``text`` None until then)."""
        st = _storage()
        if extract.is_document(rel):
            data = st.read_bytes(rel)
            h = self._bytes_hash(data)
            return {"source": source, "document": rel, "title": "", "url": "", "text": None, "hash": h}
        text = st.read_text(rel)
        return {"source": source, "document": rel, "title": title_of(rel, text), "url": "", "text": text}

    def _load(self, d: Dict[str, Any]) -> None:
        """Fill in a document's text (PDF, Word): raises ExtractorMissing or ValueError."""
        if d.get("text") is not None:
            return
        text, title = extract.extract_text(d["document"], _storage().read_bytes(d["document"]))
        d["text"] = text
        d["title"] = title or title_of(d["document"], text if d["document"].lower().endswith(".docx") else "")

    def discover(self) -> List[Dict[str, Any]]:
        """Every document to index: {source, document, title, url, text[, hash]}."""
        return list(self.iter_documents())

    def iter_documents(self) -> Iterator[Dict[str, Any]]:
        """``discover()`` one document at a time (the build holds one document's text at once)."""
        st = _storage()
        if self.settings.index_sajha_docs:
            from sajha.web.guides import guide_files, guide_url
            for rel in guide_files():
                try:
                    text = st.read_text(rel)
                except Exception:
                    continue
                name = rel.rsplit("/", 1)[-1]
                yield {"source": SAJHA_DOCS, "document": rel, "title": title_of(name, text),
                       "url": guide_url(name), "text": text}
        for src in self.settings.sources:
            try:
                files = st.list_files(src.path.rstrip("/"), src.pattern)
            except Exception as e:
                logger.warning(f"rag: source {src.name}: cannot list {src.path}: {e}")
                continue
            for rel in files:
                if not rel.lower().endswith(SUPPORTED_TYPES):
                    continue
                try:
                    d = self._file(src.name, rel)
                except Exception as e:
                    logger.warning(f"rag: source {src.name}: cannot read {rel}: {e}")
                    continue
                yield d
        for rel in self.uploads():
            try:
                d = self._file(UPLOADS, rel)
            except Exception:
                continue
            yield d

    def uploads(self) -> List[str]:
        d = self.settings.uploads_dir.rstrip("/")
        try:
            return [r for r in _storage().list_files(d, "*") if r.lower().endswith(SUPPORTED_TYPES)]
        except Exception:
            return []

    def _doc_hash(self, text: str) -> str:
        s = self.settings
        return hashlib.sha256(f"{s.chunk_chars}\x00{s.chunk_overlap}\x00{text}".encode("utf-8")).hexdigest()

    def _bytes_hash(self, data: bytes) -> str:
        s = self.settings
        return hashlib.sha256(f"{s.chunk_chars}\x00{s.chunk_overlap}\x00bin\x00".encode() + data).hexdigest()

    # ── building ────────────────────────────────────────────────
    def build(self, force: bool = False) -> Dict[str, Any]:
        """Sync the store with the documents: embed new and changed ones, drop removed ones."""
        with self._lock:
            if self._building:
                return {"status": "already building"}
            self._building = True
        t0 = time.time()
        try:
            try:
                stats = self._sync(force)
            except DimensionChanged as e:
                logger.info(f"  RAG: the embedding dimension changed ({e}); rebuilding the index")
                self.store.clear()
                stats = self._sync(True)
            stats.update(store=self.store.name, duration_ms=int((time.time() - t0) * 1000), at=time.time())
            self.last_build = stats
            logger.info(f"  RAG: {stats['documents']} documents ({stats['indexed']} indexed, {stats['unchanged']} "
                        f"unchanged, {stats['removed']} removed) in {stats['duration_ms']} ms, "
                        f"store={self.store.name}, embedder={stats['embedder']}")
            return stats
        finally:
            with self._lock:
                self._building = False
            self._built.set()

    def _sync(self, force: bool) -> Dict[str, Any]:
        stats: Dict[str, Any] = {"documents": 0, "indexed": 0, "unchanged": 0, "removed": 0, "chunks": 0,
                                 "errors": []}
        embedder = self.embedder_name()
        if not self.store.documents():
            self.store.load(embedder)
        if force or self.store.embedder() not in ("", embedder):
            self.store.clear()
        have = self.store.documents()
        seen = set()
        for d in self.iter_documents():
            stats["documents"] += 1
            key = (d["source"], d["document"])
            seen.add(key)
            h = d.get("hash") or self._doc_hash(d["text"])
            if have.get(key) == h:
                stats["unchanged"] += 1
                continue
            try:
                self._load(d)
                n = self._index_document(d, h, embedder)
                stats["indexed"] += 1
                stats["chunks"] += n
            except DimensionChanged:
                raise
            except Exception as e:
                stats["errors"].append(f"{d['document']}: {e}"[:300])
                logger.warning(f"rag: cannot index {d['document']}: {e}")
        for key in set(have) - seen:
            self.store.delete_document(*key)
            stats["removed"] += 1
        self.store.save()
        stats["embedder"] = embedder or "none (BM25 only)"
        return stats

    def _index_document(self, d: Dict[str, Any], doc_hash: str, embedder: str) -> int:
        """Chunk one document and stream its passages to the store, embedding them
        ``ai.rag.embed_batch_size`` at a time."""
        s = self.settings
        pieces = chunk_document(d["document"], d["text"], s.chunk_chars, s.chunk_overlap)
        size = max(1, int(s.embed_batch_size or 64))
        count = [0]

        def passages() -> Iterator[StoredChunk]:
            for i in range(0, len(pieces), size):
                batch = []
                for p in pieces[i:i + size]:
                    cid = hashlib.sha1(f"{d['source']}\x00{d['document']}\x00{p.ordinal}\x00{doc_hash}"
                                       .encode()).hexdigest()[:32]
                    url = d["url"] + ("#" + p.anchor if d["url"] and p.anchor else "")
                    batch.append(StoredChunk(cid, d["source"], d["document"], d["title"], p.heading, p.anchor, url,
                                             p.text, p.ordinal))
                if embedder:
                    vecs = self._embed([f"{c.title} — {c.heading}\n{c.text}" for c in batch], "document")
                    for c, v in zip(batch, vecs):
                        c.vector = v
                count[0] += len(batch)
                yield from batch

        self.store.replace_document(d["source"], d["document"], doc_hash, embedder, passages())
        return count[0]

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
                qv = self._embed([query], "query")[0]
                w = max(0.0, float(self.settings.vector_weight))
                for rank, (c, _score) in enumerate(self.store.search(qv, pool, sources)):
                    ranked[c.id] = ranked.get(c.id, 0.0) + w / (_RRF_K + rank + 1)
                    found[c.id] = c
            except Exception as e:
                logger.info(f"rag: vector search failed ({e}); lexical only")
        try:
            hits = self.store.keyword_search(query, pool, sources)
        except Exception as e:
            logger.info(f"rag: keyword search failed ({e})")
            hits = []
        for rank, (c, _score) in enumerate(hits):
            ranked[c.id] = ranked.get(c.id, 0.0) + 1.0 / (_RRF_K + rank + 1)
            found.setdefault(c.id, c)
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
        rel = f"{self.settings.uploads_dir.rstrip('/')}/{name}"
        if extract.is_document(name):         # PDF / Word: read it before keeping it
            try:
                text, title = extract.extract_text(name, data)
            except extract.ExtractorMissing as e:
                raise ValueError(str(e))
            _storage().write_bytes(rel, data)
            d = {"source": UPLOADS, "document": rel, "url": "", "text": text,
                 "title": title or title_of(rel, text if name.lower().endswith(".docx") else "")}
            h = self._bytes_hash(data)
        else:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("file is not UTF-8 text")
            _storage().write_text(rel, text)
            d = {"source": UPLOADS, "document": rel, "title": title_of(rel, text), "url": "", "text": text}
            h = self._doc_hash(text)
        n = self._index_document(d, h, self.store.embedder() or self.embedder_name())
        self.store.save()
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
        return True

    def stats(self) -> Dict[str, Any]:
        out = self.store.stats()
        out.update(embedder=self.store.embedder() or "none (BM25 only)", built=self._built.is_set(),
                   building=self._building, last_build=self.last_build, uploads=self.uploads(),
                   configured_sources=[s.model_dump() for s in self.settings.sources],
                   document_readers=extract.available(),
                   index_sajha_docs=self.settings.index_sajha_docs,
                   store_configured=self.settings.store, store_fallback=self.store_fallback)
        return out


# ── singleton ─────────────────────────────────────────────────────

_index: Optional[DocIndex] = None


def init_doc_index(settings: Optional[RagSettings] = None, gateway=None) -> Optional[DocIndex]:
    global _index
    settings = settings or RagSettings()
    if _index is not None:
        _index.close()
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
