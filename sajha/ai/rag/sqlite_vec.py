"""
SAJHA MCP Server — RAG: the sqlite-vec store (``ai.rag.store: sqlite_vec``, the default via ``auto``).
Copyright All rights Reserved 2025-2030, Ashutosh Sinha

One SQLite file of its own (``ai.rag.stores.sqlite_vec.path``, default ``data/rag/vectors.db``),
opened with Python's ``sqlite3`` and never through SAJHA's database engine, so the document
index never shares a file, a lock or a schema with ``sajha.db``. In that file:

* ``rag_documents``: one row per document (source, path, content hash, title, url);
* ``rag_chunks``: the passages' text and citation metadata;
* ``rag_fts``: an FTS5 index over the passages (external content, kept in step by triggers),
  the keyword (BM25) side of the hybrid search;
* ``rag_vec``: a sqlite-vec ``vec0`` table of float32 embeddings (cosine distance) with the
  source as a metadata column, created on the first vector with the embedder's dimension;
* ``rag_meta``: schema version, embedder and dimension. A different embedder clears the
  store; a different dimension under the same embedder raises ``DimensionChanged`` (DocIndex
  rebuilds from scratch).

Both searches run inside SQLite and only the top k rows reach Python, so the process holds no
copy of the corpus. The file is in WAL mode: one writer connection (behind a lock) and one
reader connection per thread, so searches proceed while the index is being built. With
``ai.rag.persist: false`` the store is a temporary file removed when the store closes.
Keyword-only mode (``ai.rag.embedding_model: none``) never creates ``rag_vec``.

Needs the ``sqlite-vec`` package and a Python whose ``sqlite3`` allows ``load_extension``;
``probe()`` names what is missing and ``auto`` then falls back to the memory store.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
import threading
import weakref
from typing import List, Optional, Tuple

from sajha.ai.rag.stores import (DimensionChanged, StoreUnavailable, StoredChunk, VectorStore, keyword_terms,
                                 normalize)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
_COLS = "c.id, c.source, c.document, c.title, c.heading, c.anchor, c.url, c.text, c.ordinal"

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS rag_documents (source TEXT NOT NULL, document TEXT NOT NULL, doc_hash TEXT NOT NULL, "
    "title TEXT, url TEXT, PRIMARY KEY (source, document))",
    "CREATE TABLE IF NOT EXISTS rag_chunks (rid INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, source TEXT NOT NULL, "
    "document TEXT NOT NULL, ordinal INTEGER NOT NULL, title TEXT, heading TEXT, anchor TEXT, url TEXT, "
    "text TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS ix_rag_chunks_document ON rag_chunks (source, document)",
    "CREATE VIRTUAL TABLE IF NOT EXISTS rag_fts USING fts5(title, heading, text, content='rag_chunks', "
    "content_rowid='rid', tokenize='porter unicode61')",
    "CREATE TRIGGER IF NOT EXISTS rag_chunks_ai AFTER INSERT ON rag_chunks BEGIN "
    "INSERT INTO rag_fts (rowid, title, heading, text) VALUES (new.rid, new.title, new.heading, new.text); END",
    "CREATE TRIGGER IF NOT EXISTS rag_chunks_ad AFTER DELETE ON rag_chunks BEGIN "
    "INSERT INTO rag_fts (rag_fts, rowid, title, heading, text) VALUES ('delete', old.rid, old.title, old.heading, "
    "old.text); END",
]
_DROP = ["DROP TABLE IF EXISTS rag_vec", "DROP TRIGGER IF EXISTS rag_chunks_ai", "DROP TRIGGER IF EXISTS rag_chunks_ad",
         "DROP TABLE IF EXISTS rag_fts", "DROP TABLE IF EXISTS rag_chunks", "DROP TABLE IF EXISTS rag_documents",
         "DELETE FROM rag_meta"]


def _load_vec(conn: sqlite3.Connection) -> None:
    """Load sqlite-vec into ``conn``; StoreUnavailable names what is missing."""
    try:
        import sqlite_vec
    except ImportError:
        raise StoreUnavailable("the sqlite-vec package is not installed (pip install sqlite-vec)") from None
    if not hasattr(conn, "enable_load_extension"):
        raise StoreUnavailable("this Python's sqlite3 module cannot load extensions (it was built with "
                               "SQLITE_OMIT_LOAD_EXTENSION; use a Python built with loadable extensions)")
    try:
        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
    except StoreUnavailable:
        raise
    except Exception as e:
        raise StoreUnavailable(f"sqlite-vec did not load into SQLite {sqlite3.sqlite_version}: {e}") from None


def _cleanup(readers: List[sqlite3.Connection], writer: sqlite3.Connection, temp_path: Optional[str]) -> None:
    """Close the connections; remove a temporary store's files (at close, collection or exit)."""
    for conn in list(readers) + [writer]:
        try:
            conn.close()
        except Exception:
            pass
    readers.clear()
    if temp_path:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(temp_path + suffix)
            except OSError:
                pass


def _serialize(v) -> bytes:
    from array import array
    return array("f", v).tobytes()


class SqliteVecStore(VectorStore):
    name = "sqlite_vec"
    defaults = {"path": "data/rag/vectors.db"}

    def __init__(self, path: str, temporary: bool = False):
        if not path or path == ":memory:" or path.startswith("file:"):
            raise ValueError("ai.rag.stores.sqlite_vec.path must be a file path")
        self.path = os.path.abspath(path)
        self.temporary = temporary
        self._guard_against_sajha_db()
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        self._local = threading.local()
        self._readers: List[sqlite3.Connection] = []
        self._closed = False
        self._w = self._connect(check_same_thread=False)
        self._w.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self._open_schema()
        self._finalizer = weakref.finalize(self, _cleanup, self._readers, self._w,
                                           self.path if temporary else None)

    # ── lifecycle ───────────────────────────────────────────────
    @classmethod
    def probe(cls, options):
        try:
            conn = sqlite3.connect(":memory:")
            try:
                _load_vec(conn)
                conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
            except sqlite3.Error as e:
                return f"SQLite {sqlite3.sqlite_version} has no FTS5 ({e})"
            finally:
                conn.close()
        except StoreUnavailable as e:
            return str(e)
        return None

    @classmethod
    def create(cls, options, settings=None, engine=None):
        reason = cls.probe(options)
        if reason:
            raise StoreUnavailable(reason)
        if settings is not None and not settings.persist:
            fd, path = tempfile.mkstemp(prefix="sajha-rag-", suffix=".db")
            os.close(fd)
            return cls(path, temporary=True)
        return cls(str(options.get("path") or cls.defaults["path"]))

    def _guard_against_sajha_db(self) -> None:
        """The document index never lives in SAJHA's own SQLite database."""
        try:
            from sajha.db.engine import get_engine
            url = get_engine().url
        except Exception:
            return
        if url.get_backend_name() == "sqlite" and url.database and \
                os.path.realpath(url.database) == os.path.realpath(self.path):
            raise StoreUnavailable(f"ai.rag.stores.sqlite_vec.path {self.path} is SAJHA's own database; "
                                   "give the document index a file of its own")

    def _connect(self, check_same_thread: bool = True) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=check_same_thread, timeout=30)
        _load_vec(conn)
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _r(self) -> sqlite3.Connection:
        """This thread's reader connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            if self._closed:
                raise RuntimeError("the sqlite_vec store is closed")
            conn = self._connect(check_same_thread=False)    # closed from whichever thread closes the store
            self._local.conn = conn
            with self._lock:
                self._readers.append(conn)
        return conn

    def _open_schema(self) -> None:
        w = self._w
        w.execute("CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        version = self._meta_w("schema")
        if version not in (None, SCHEMA_VERSION):
            logger.info(f"rag: {self.path} has schema {version}; rebuilding it")
            for stmt in _DROP:
                w.execute(stmt)
        for stmt in _SCHEMA:
            w.execute(stmt)
        w.execute("INSERT OR REPLACE INTO rag_meta VALUES ('schema', ?)", (SCHEMA_VERSION,))

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._finalizer()

    # ── meta ────────────────────────────────────────────────────
    def _meta_w(self, key: str) -> Optional[str]:
        r = self._w.execute("SELECT value FROM rag_meta WHERE key = ?", (key,)).fetchone()
        return r[0] if r else None

    def _set_meta(self, key: str, value: str) -> None:
        self._w.execute("INSERT OR REPLACE INTO rag_meta VALUES (?, ?)", (key, value))

    def embedder(self) -> str:
        r = self._r().execute("SELECT value FROM rag_meta WHERE key = 'embedder'").fetchone()
        return r[0] if r else ""

    def dimensions(self) -> int:
        r = self._r().execute("SELECT value FROM rag_meta WHERE key = 'dim'").fetchone()
        return int(r[0]) if r else 0

    # ── writing ─────────────────────────────────────────────────
    def _clear_locked(self) -> None:
        for stmt in _DROP:
            self._w.execute(stmt)
        for stmt in _SCHEMA:
            self._w.execute(stmt)
        self._set_meta("schema", SCHEMA_VERSION)

    def _has_vec(self) -> bool:
        return self._w.execute("SELECT 1 FROM sqlite_master WHERE name = 'rag_vec'").fetchone() is not None

    def _ensure_vec(self, dim: int, source: str, document: str) -> None:
        have = int(self._meta_w("dim") or 0)
        if have == dim and self._has_vec():
            return
        if have and have != dim:
            others = self._w.execute("SELECT 1 FROM rag_documents WHERE NOT (source = ? AND document = ?) LIMIT 1",
                                     (source, document)).fetchone()
            if others:
                raise DimensionChanged(f"vectors of {dim} dimensions; the store holds {have}")
        self._w.execute("DROP TABLE IF EXISTS rag_vec")
        self._w.execute(f"CREATE VIRTUAL TABLE rag_vec USING vec0(embedding float[{int(dim)}] "
                        "distance_metric=cosine, source text)")
        self._set_meta("dim", str(int(dim)))

    def _delete_locked(self, source: str, document: str) -> None:
        w = self._w
        if self._has_vec():
            w.execute("DELETE FROM rag_vec WHERE rowid IN (SELECT rid FROM rag_chunks WHERE source = ? AND document = ?)",
                      (source, document))
        w.execute("DELETE FROM rag_chunks WHERE source = ? AND document = ?", (source, document))
        w.execute("DELETE FROM rag_documents WHERE source = ? AND document = ?", (source, document))

    def replace_document(self, source, document, doc_hash, embedder, chunks):
        n = 0
        with self._lock:
            w = self._w
            w.execute("BEGIN IMMEDIATE")
            try:
                stored = self._meta_w("embedder") or ""
                if stored != embedder and w.execute("SELECT 1 FROM rag_documents LIMIT 1").fetchone():
                    self._clear_locked()
                self._set_meta("embedder", embedder)
                self._delete_locked(source, document)
                first = True
                for c in chunks:
                    if first:
                        w.execute("INSERT INTO rag_documents VALUES (?, ?, ?, ?, ?)",
                                  (source, document, doc_hash, c.title, c.url.split("#", 1)[0]))
                        first = False
                    rid = w.execute("INSERT INTO rag_chunks (id, source, document, ordinal, title, heading, anchor, url, "
                                    "text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                    (c.id, source, document, c.ordinal, c.title, c.heading, c.anchor, c.url,
                                     c.text)).lastrowid
                    if len(c.vector):
                        self._ensure_vec(len(c.vector), source, document)
                        w.execute("INSERT INTO rag_vec (rowid, embedding, source) VALUES (?, ?, ?)",
                                  (rid, _serialize(c.vector), source))
                    n += 1
                if first:
                    w.execute("INSERT INTO rag_documents VALUES (?, ?, ?, '', '')", (source, document, doc_hash))
                w.execute("COMMIT")
            except BaseException:
                w.execute("ROLLBACK")
                raise
        return n

    def delete_document(self, source, document):
        with self._lock:
            self._w.execute("BEGIN IMMEDIATE")
            try:
                self._delete_locked(source, document)
                self._w.execute("COMMIT")
            except BaseException:
                self._w.execute("ROLLBACK")
                raise

    def clear(self):
        with self._lock:
            self._w.execute("BEGIN IMMEDIATE")
            try:
                self._clear_locked()
                self._w.execute("COMMIT")
            except BaseException:
                self._w.execute("ROLLBACK")
                raise

    # ── reading ─────────────────────────────────────────────────
    def documents(self):
        rows = self._r().execute("SELECT source, document, doc_hash FROM rag_documents").fetchall()
        return {(r[0], r[1]): r[2] for r in rows}

    @staticmethod
    def _chunk(r) -> StoredChunk:
        return StoredChunk(r[0], r[1], r[2], r[3] or "", r[4] or "", r[5] or "", r[6] or "", r[7], r[8])

    @staticmethod
    def _in(sources) -> Tuple[str, List[str]]:
        sources = list(sources or [])
        return ",".join("?" * len(sources)), sources

    def chunks(self):
        cur = self._r().execute(f"SELECT {_COLS} FROM rag_chunks c ORDER BY c.rid")
        for r in cur:
            yield self._chunk(r)

    def search(self, vector, top_k, sources=None):
        q = normalize(vector)
        conn = self._r()
        if not q or not top_k or conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'rag_vec'").fetchone() is None:
            return []
        dim = self.dimensions()
        if dim and dim != len(q):
            raise DimensionChanged(f"a {len(q)}-dimension query against {dim}-dimension vectors")
        where, args = "", []
        if sources:
            marks, args = self._in(sources)
            where = f" AND source IN ({marks})"
        rows = conn.execute(
            f"SELECT {_COLS}, v.distance FROM (SELECT rowid, distance FROM rag_vec WHERE embedding MATCH ? "
            f"AND k = ?{where}) v JOIN rag_chunks c ON c.rid = v.rowid ORDER BY v.distance",
            [_serialize(q), min(int(top_k), 4096), *args]).fetchall()
        return [(self._chunk(r), 1.0 - float(r[9])) for r in rows]

    def keyword_search(self, query, top_k, sources=None):
        terms = keyword_terms(query)
        if not terms or not top_k:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        where, args = "", []
        if sources:
            marks, args = self._in(sources)
            where = f" AND c.source IN ({marks})"
        rows = self._r().execute(
            f"SELECT {_COLS}, rag_fts.rank FROM rag_fts JOIN rag_chunks c ON c.rid = rag_fts.rowid "
            f"WHERE rag_fts MATCH ?{where} ORDER BY rag_fts.rank LIMIT ?",
            [match, *args, int(top_k)]).fetchall()
        return [(self._chunk(r), -float(r[9])) for r in rows]     # FTS5 rank: bm25(), lower is better

    def stats(self):
        out = super().stats()
        conn = self._r()
        out.update(chunks=conn.execute("SELECT count(*) FROM rag_chunks").fetchone()[0],
                   dimensions=self.dimensions(), path=None if self.temporary else self.path,
                   bytes=sum(os.path.getsize(self.path + s) for s in ("", "-wal") if os.path.exists(self.path + s)))
        return out
